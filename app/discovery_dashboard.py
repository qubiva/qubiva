"""
Enhanced Discovery Manager - Adds historical data support and better parsing
This extends the existing DiscoveryManager with dashboard-specific features
"""

from typing import Dict, List, Tuple, Any
from datetime import datetime
import logging
import os
import json

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class DiscoveryDashboard:
    """
    Enhanced version of DiscoveryManager with:
    - Historical discovery retrieval
    - Better resource parsing (tags, regions, etc.)
    - Tagging compliance analysis
    - Multiple discovery comparison
    """

    def __init__(self, db_manager, config_manager):
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.artifacts_base = os.getenv('ARTIFACTS_STORAGE_PATH', '/app/data/artifacts')
        self.artifacts_prefix = os.getenv('ARTIFACTS_PREFIX', 'query-results')
        self.collection_name = 'discovery_configs'

    # ==================== Historical Data Retrieval ====================

    async def get_discovery_history(
        self,
        project_name: str,
        cloud_platform: str,
        account_id: str,
        request_tracker,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get historical discoveries for an account.
        """
        try:
            success, result = await request_tracker.list_requests(
                project_name=project_name,
                request_type="discovery_run",
                page=1,
                page_size=limit,
                custom_filter={
                    "cloud_account": account_id,
                    "cloud_platform": cloud_platform,
                    "state": "completed"
                }
            )

            if not success or not result.get("runs"):
                logger.info(f"No discovery history found for {account_id}")
                return []

            discoveries = result["runs"]
            history = []

            for discovery in discoveries:
                request_id = discovery.get("request_id")
                discovered_at = discovery.get("requested_on")

                try:
                    summary = await self._get_discovery_summary(request_id)
                    history.append({
                        "request_id": request_id,
                        "discovered_at": discovered_at,
                        "total_resources": summary.get("total_resources", 0),
                        "total_cost": summary.get("total_cost", 0.0),
                        "status": "success"
                    })
                except Exception as e:
                    logger.warning(f"Failed to get summary for {request_id}: {str(e)}")
                    history.append({
                        "request_id": request_id,
                        "discovered_at": discovered_at,
                        "total_resources": 0,
                        "total_cost": 0.0,
                        "status": "incomplete"
                    })

            logger.info(f"Retrieved {len(history)} discoveries for {account_id}")
            return history

        except Exception as e:
            logger.error(f"Failed to get discovery history: {str(e)}")
            return []

    async def _get_discovery_summary(self, request_id: str) -> Dict[str, Any]:
        """Get basic summary from a discovery JSON file."""
        base_path = os.path.join(self.artifacts_base, self.artifacts_prefix, request_id)

        if not os.path.isdir(base_path):
            raise ValueError(f"No files found for request_id: {request_id}")

        # Find discovery JSON file
        discovery_file = None
        for filename in os.listdir(base_path):
            if 'discovery_' in filename and filename.endswith('.json'):
                discovery_file = os.path.join(base_path, filename)
                break

        if not discovery_file:
            raise ValueError(f"Discovery JSON not found for request_id: {request_id}")

        with open(discovery_file, 'r') as f:
            discovery_data = json.load(f)

        resources = discovery_data.get('resources', {}).get('rows', [])
        costs = discovery_data.get('costs', {}).get('rows', [])

        total_resources = len(resources)
        total_cost = sum(float(c.get('total_cost', 0)) for c in costs)

        return {
            "total_resources": total_resources,
            "total_cost": round(total_cost, 2)
        }

    async def get_full_discovery_data(
        self,
        request_id: str
    ) -> Tuple[bool, int, Any]:
        """Get full discovery data for a specific request_id."""
        try:
            base_path = os.path.join(self.artifacts_base, self.artifacts_prefix, request_id)

            if not os.path.isdir(base_path):
                return False, 404, "Discovery not found"

            discovery_file = None
            for filename in os.listdir(base_path):
                if 'discovery_' in filename and filename.endswith('.json'):
                    discovery_file = os.path.join(base_path, filename)
                    break

            if not discovery_file:
                return False, 404, "Discovery JSON not found"

            with open(discovery_file, 'r') as f:
                discovery_data = json.load(f)

            structured_data = self._parse_discovery_data_enhanced(
                discovery_data,
                request_id
            )

            return True, 200, structured_data

        except Exception as e:
            logger.error(f"Failed to get full discovery data: {str(e)}")
            return False, 500, f"Failed to retrieve discovery: {str(e)}"

    # ==================== Enhanced Data Parsing ====================

    def _parse_discovery_data_enhanced(
        self,
        discovery_data: Dict,
        request_id: str,
        discovered_at: str = None
    ) -> Dict[str, Any]:
        """
        Enhanced parsing with:
        - Region/location breakdown
        - Tagging compliance
        - Normalized resource list
        - Better tag handling (JSON string to dict)
        """
        resources_raw = discovery_data.get('resources', {}).get('rows', [])
        costs_raw = discovery_data.get('costs', {}).get('rows', [])

        resources = []
        resources_by_type = {}
        resources_by_region = {}
        tagged_count = 0
        untagged_count = 0

        for resource in resources_raw:
            tags = self._parse_tags(resource.get('tags', '{}'))

            if tags and len(tags) > 0:
                tagged_count += 1
            else:
                untagged_count += 1

            normalized = {
                'resource_type': resource.get('resource_type', 'unknown'),
                'resource_id': resource.get('resource_id', 'unknown'),
                'resource_name': resource.get('resource_name', 'unknown'),
                'region': resource.get('region', 'global'),
                'tags': tags,
                'account_id': resource.get('account_id', 'unknown')
            }

            resources.append(normalized)

            resource_type = normalized['resource_type']
            if resource_type not in resources_by_type:
                resources_by_type[resource_type] = []
            resources_by_type[resource_type].append(normalized)

            region = normalized['region']
            if region not in resources_by_region:
                resources_by_region[region] = 0
            resources_by_region[region] += 1

        total_cost = 0
        cost_by_service = {}

        for cost_item in costs_raw:
            service = cost_item.get('service')
            if not service:
                continue

            cost = float(cost_item.get('total_cost', 0))

            if service not in cost_by_service:
                cost_by_service[service] = 0
            cost_by_service[service] += cost
            total_cost += cost

        cost_by_service = {
            service: round(cost, 2)
            for service, cost in cost_by_service.items()
        }

        resource_summary = {
            resource_type: len(items)
            for resource_type, items in resources_by_type.items()
        }

        total_resources = len(resources)
        tagging_compliance = {
            'tagged': tagged_count,
            'untagged': untagged_count,
            'total': total_resources,
            'compliance_pct': round((tagged_count / total_resources * 100), 1) if total_resources > 0 else 0
        }

        return {
            "request_id": request_id,
            "discovered_at": discovered_at or discovery_data.get('discovered_at', datetime.utcnow().isoformat()),
            "summary": {
                "total_resources": total_resources,
                "total_cost": round(total_cost, 2),
                "currency": "USD",
                "by_type": resource_summary,
                "by_region": resources_by_region,
                "by_service_cost": cost_by_service,
                "tagging": tagging_compliance
            },
            "resources": resources,
            "resources_by_type": resources_by_type
        }

    def _parse_tags(self, tags_input: Any) -> Dict[str, str]:
        """Parse tags which might be JSON string, dict, or empty."""
        if not tags_input:
            return {}

        if isinstance(tags_input, dict):
            return tags_input

        if isinstance(tags_input, str):
            try:
                parsed = json.loads(tags_input)
                return parsed if isinstance(parsed, dict) else {}
            except (json.JSONDecodeError, ValueError):
                logger.warning(f"Failed to parse tags: {tags_input}")
                return {}

        return {}

    # ==================== Comparison Features ====================

    async def compare_discoveries(
        self,
        request_id_1: str,
        request_id_2: str
    ) -> Tuple[bool, int, Any]:
        """Compare two discoveries and return differences."""
        try:
            success1, _, data1 = await self.get_full_discovery_data(request_id_1)
            success2, _, data2 = await self.get_full_discovery_data(request_id_2)

            if not success1 or not success2:
                return False, 404, "One or both discoveries not found"

            diff = {
                "discovery_1": {
                    "request_id": request_id_1,
                    "discovered_at": data1["discovered_at"],
                    "total_resources": data1["summary"]["total_resources"],
                    "total_cost": data1["summary"]["total_cost"]
                },
                "discovery_2": {
                    "request_id": request_id_2,
                    "discovered_at": data2["discovered_at"],
                    "total_resources": data2["summary"]["total_resources"],
                    "total_cost": data2["summary"]["total_cost"]
                },
                "changes": {
                    "resources_delta": data2["summary"]["total_resources"] - data1["summary"]["total_resources"],
                    "cost_delta": round(data2["summary"]["total_cost"] - data1["summary"]["total_cost"], 2),
                    "cost_delta_pct": self._calculate_percent_change(
                        data1["summary"]["total_cost"],
                        data2["summary"]["total_cost"]
                    )
                }
            }

            return True, 200, diff

        except Exception as e:
            logger.error(f"Failed to compare discoveries: {str(e)}")
            return False, 500, f"Comparison failed: {str(e)}"

    def _calculate_percent_change(self, old_value: float, new_value: float) -> float:
        """Calculate percentage change between two values."""
        if old_value == 0:
            return 100.0 if new_value > 0 else 0.0
        return round(((new_value - old_value) / old_value) * 100, 1)

    async def get_latest_discovery_data(
        self,
        project_name: str,
        cloud_platform: str,
        account_id: str,
        request_tracker
    ) -> Tuple[bool, int, Any]:
        """Get the latest discovery data with enhanced parsing."""
        try:
            history = await self.get_discovery_history(
                project_name=project_name,
                cloud_platform=cloud_platform,
                account_id=account_id,
                request_tracker=request_tracker,
                limit=1
            )

            if not history or len(history) == 0:
                return False, 404, "No discovery data found"

            latest = history[0]
            request_id = latest["request_id"]

            return await self.get_full_discovery_data(request_id)

        except Exception as e:
            logger.error(f"Failed to get latest discovery: {str(e)}")
            return False, 500, f"Failed to retrieve latest discovery: {str(e)}"
