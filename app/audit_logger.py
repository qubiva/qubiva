"""
Audit logger — pushes structured audit events to Loki.

Every mutation (create/update/delete) on Qubiva resources is logged
as a structured JSON event to Loki with the label {log_type="audit"}.
This provides an immutable, queryable audit trail of who did what, when.

Audit events have their own retention period (configurable separately
from runner logs) and are queryable by the Cloud Analyst AI via the
get_audit_log tool.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger('uvicorn.error')


class AuditLogger:
    """Pushes audit events to Loki for long-term retention and querying."""

    def __init__(self, loki_url: str = None, config_manager=None):
        import os
        self.loki_url = loki_url or os.environ.get(
            'LOKI_URL', 'http://loki.qubiva.svc.cluster.local:3100'
        )
        self.config_manager = config_manager
        self._client = None

    def _get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def log_event(
        self,
        action: str,
        user: str,
        target_type: str,
        target_id: str = "",
        project_name: str = "",
        details: Optional[dict] = None,
    ):
        """Push a single audit event to Loki.

        Args:
            action: What happened (e.g., "create_project", "update_credential",
                    "delete_cloud_account", "add_member").
            user: Who performed the action (username/email).
            target_type: Type of resource (e.g., "project", "cloud_account",
                         "credential", "workspace", "user", "github_repo").
            target_id: Identifier of the affected resource.
            project_name: Project context (empty for org-level operations).
            details: Optional dict with extra context (changed fields, etc.).
        """
        timestamp_ns = int(time.time() * 1e9)
        event = {
            "action": action,
            "user": user,
            "target_type": target_type,
            "target_id": target_id,
            "project_name": project_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if details:
            event["details"] = details

        payload = {
            "streams": [
                {
                    "stream": {
                        "app": "qubiva",
                        "log_type": "audit",
                        "action": action,
                        "target_type": target_type,
                        "project": project_name or "_org",
                    },
                    "values": [
                        [str(timestamp_ns), json.dumps(event)]
                    ],
                }
            ]
        }

        try:
            client = self._get_client()
            resp = await client.post(
                f"{self.loki_url}/loki/api/v1/push",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code not in (200, 204):
                logger.warning(
                    "Audit push to Loki failed (%s): %s",
                    resp.status_code, resp.text[:200],
                )
        except Exception as e:
            # Audit logging should never break the request flow
            logger.warning("Failed to push audit event to Loki: %s", e)

    async def query_events(
        self,
        project_name: str = "",
        target_type: str = "",
        action: str = "",
        user: str = "",
        limit: int = 100,
        days_back: int = 30,
    ) -> list:
        """Query audit events from Loki.

        Returns a list of parsed audit event dicts, newest first.
        """
        # Build LogQL label selector
        labels = ['log_type="audit"', 'app="qubiva"']
        if project_name:
            labels.append(f'project="{project_name}"')
        if target_type:
            labels.append(f'target_type="{target_type}"')
        if action:
            labels.append(f'action="{action}"')

        selector = "{" + ", ".join(labels) + "}"

        # Add optional line filter for user
        if user:
            selector += f' |= "{user}"'

        try:
            client = self._get_client()
            end = datetime.now(timezone.utc)
            start_dt = end - __import__('datetime').timedelta(days=days_back)

            params = {
                "query": selector,
                "direction": "backward",
                "limit": limit,
                "start": str(int(start_dt.timestamp() * 1e9)),
                "end": str(int(end.timestamp() * 1e9)),
            }

            resp = await client.get(
                f"{self.loki_url}/loki/api/v1/query_range",
                params=params,
            )

            if resp.status_code != 200:
                logger.warning("Audit query failed (%s): %s", resp.status_code, resp.text[:200])
                return []

            data = resp.json()
            result = data.get("data", {}).get("result", [])

            events = []
            for stream in result:
                for ts, line in stream.get("values", []):
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        events.append({"raw": line})

            # Sort by timestamp descending (newest first)
            events.sort(
                key=lambda e: e.get("timestamp", ""),
                reverse=True,
            )
            return events[:limit]

        except Exception as e:
            logger.warning("Failed to query audit events from Loki: %s", e)
            return []

    async def close(self):
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
