"""
Log persistence service using Loki for runner job log storage and retrieval.

Supports per-job-type configurable retention with automatic cleanup.
Job types: terraform, discovery (each with independent retention period).
"""
import logging
import os
import time
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger('uvicorn.error')


# Map request_type values (from MongoDB) to job_type categories for retention
REQUEST_TYPE_TO_JOB_TYPE = {
    'terraform_run': 'terraform',
    'query_run': 'discovery',
    'discovery_run': 'discovery',
    'benchmark_run': 'discovery',
}

DEFAULT_RETENTION_DAYS = {
    'terraform': 90,
    'discovery': 30,
    'default': 30,
}


class LogPersistenceService:
    """
    Manages log storage in Loki for runner job logs.

    Push: Store pod logs after job completes/fails
    Query: Retrieve historical logs by request_id
    Retention: Periodic cleanup based on per-type config
    """

    def __init__(self, config_manager=None):
        self.loki_url = os.environ.get(
            'LOKI_URL', 'http://loki.qubiva.svc.cluster.local:3100'
        )
        self.config_manager = config_manager
        self._client = None

    def _get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    def get_retention_days(self, job_type: str) -> int:
        """Get retention days for a specific job type.

        Resolution order:
        1. Environment variable: LOG_RETENTION_DAYS_TERRAFORM, etc.
        2. app_config.json: system.log_retention.terraform, etc.
        3. Built-in defaults
        """
        # 1. Check env var: LOG_RETENTION_DAYS_TERRAFORM
        env_key = f"LOG_RETENTION_DAYS_{job_type.upper()}"
        env_val = os.environ.get(env_key)
        if env_val:
            try:
                return int(env_val)
            except ValueError:
                pass

        # 2. Check app_config
        if self.config_manager:
            try:
                system_config = self.config_manager.get_config('system')
                retention = system_config.get('log_retention', {})
                if job_type in retention:
                    return int(retention[job_type])
                if 'default' in retention:
                    return int(retention['default'])
            except Exception:
                pass

        # 3. Built-in defaults
        return DEFAULT_RETENTION_DAYS.get(job_type, DEFAULT_RETENTION_DAYS['default'])

    def get_all_retention_config(self) -> dict:
        """Return retention config for all job types. Used by UI/API."""
        return {
            jt: self.get_retention_days(jt)
            for jt in ['terraform', 'discovery']
        }

    @staticmethod
    def resolve_job_type(request_type: str) -> str:
        """Map a request_type (from MongoDB) to a job_type category."""
        return REQUEST_TYPE_TO_JOB_TYPE.get(request_type, 'default')

    async def push_logs(self, request_id: str, job_type: str, project_name: str,
                        log_text: str, timestamp_ns: Optional[int] = None) -> bool:
        """Push log text to Loki with structured labels."""
        if not log_text or not log_text.strip():
            logger.debug(f"No logs to push for request {request_id}")
            return False

        if timestamp_ns is None:
            timestamp_ns = int(time.time() * 1e9)

        payload = {
            "streams": [
                {
                    "stream": {
                        "app": "qubiva",
                        "job_type": job_type,
                        "request_id": request_id,
                        "project": project_name,
                    },
                    "values": []
                }
            ]
        }

        lines = log_text.split('\n')
        for i, line in enumerate(lines):
            if line.strip():
                line_ts = str(timestamp_ns + i)
                payload["streams"][0]["values"].append([line_ts, line])

        if not payload["streams"][0]["values"]:
            return False

        try:
            client = self._get_client()
            resp = await client.post(
                f"{self.loki_url}/loki/api/v1/push",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            if resp.status_code in (200, 204):
                logger.info(f"Pushed {len(payload['streams'][0]['values'])} log lines to Loki for request {request_id}")
                return True
            else:
                logger.error(f"Loki push failed ({resp.status_code}): {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to push logs to Loki for {request_id}: {e}")
            return False

    async def query_logs(self, request_id: str, limit: int = 5000) -> Optional[str]:
        """Query logs from Loki by request_id. Returns full log text or None.

        Uses tiered time ranges: tries recent first (fast), widens if needed.
        """
        try:
            client = self._get_client()
            end = datetime.now(timezone.utc)

            # Try progressively wider ranges - most queries hit recent logs
            for days_back in (7, 30, 91):
                start = end - timedelta(days=days_back)
                params = {
                    "query": f'{{app="qubiva", request_id="{request_id}"}}',
                    "direction": "forward",
                    "limit": limit,
                    "start": str(int(start.timestamp() * 1e9)),
                    "end": str(int(end.timestamp() * 1e9)),
                }

                try:
                    resp = await client.get(
                        f"{self.loki_url}/loki/api/v1/query_range",
                        params=params,
                    )
                except Exception:
                    # Timeout or connection error - try wider range
                    continue

                if resp.status_code != 200:
                    logger.warning(f"Loki query failed ({resp.status_code}) with {days_back}d range")
                    continue

                data = resp.json()
                result = data.get("data", {}).get("result", [])

                if result:
                    all_lines = []
                    for stream in result:
                        for ts, line in stream.get("values", []):
                            all_lines.append((int(ts), line))
                    all_lines.sort(key=lambda x: x[0])
                    return '\n'.join(line for _, line in all_lines)

            return None

        except Exception as e:
            logger.error(f"Failed to query logs from Loki for {request_id}: {e}")
            return None

    async def delete_old_logs(self, job_type: str, retention_days: int) -> bool:
        """Delete logs older than retention_days for a specific job type using Loki Delete API."""
        try:
            client = self._get_client()
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

            # Delete all logs older than cutoff (from epoch start to cutoff)
            params = {
                "query": f'{{app="qubiva", job_type="{job_type}"}}',
                "start": "2020-01-01T00:00:00Z",
                "end": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

            resp = await client.post(
                f"{self.loki_url}/loki/api/v1/delete",
                params=params,
            )

            if resp.status_code in (200, 204):
                logger.info(f"Scheduled deletion of {job_type} logs older than {retention_days} days")
                return True
            else:
                logger.warning(f"Loki delete request failed ({resp.status_code}): {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to delete old {job_type} logs: {e}")
            return False

    async def enforce_retention(self):
        """Run retention enforcement for all job types. Called by scheduler daily."""
        job_types = ['terraform', 'discovery']
        for job_type in job_types:
            days = self.get_retention_days(job_type)
            await self.delete_old_logs(job_type, days)
            logger.info(f"Retention enforced for {job_type}: {days} days")

    async def is_available(self) -> bool:
        """Check if Loki is reachable."""
        try:
            client = self._get_client()
            resp = await client.get(f"{self.loki_url}/ready", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
