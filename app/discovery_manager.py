"""
Discovery Manager
Uses to_jsonb() to safely extract columns from cloud resource tables,
handling cases where columns may not exist (e.g., aws_ecs_task has no 'title')
"""

from typing import Dict, List, Tuple, Optional
from datetime import datetime
import logging
import os

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class DiscoveryManager:
    """
    Manages cloud resource discovery operations.
    Builds queries, fetches results from local filesystem, parses and structures data.
    """

    def __init__(self, db_manager, config_manager):
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.artifacts_base = os.getenv('ARTIFACTS_STORAGE_PATH', '/app/data/artifacts')
        self.artifacts_prefix = os.getenv('ARTIFACTS_PREFIX', 'query-results')
        self.collection_name = 'discovery_configs'

    # ==================== Resource Type Management ====================

    def get_available_resource_types(self, cloud_platform: str) -> Dict[str, str]:
        """
        Get available resource types from config.
        Returns dict of {table_name: description}
        """
        resource_types = self.config_manager.get_config(
            'compliance_mods',
            cloud_platform.lower(),
            'resource_types'
        )

        if not resource_types:
            logger.warning(f"No resource types found in config for platform: {cloud_platform}")
            return {}

        return resource_types

    async def get_selected_resource_types(
        self,
        project_name: str,
        cloud_platform: str,
        account_id: str
    ) -> Optional[List[str]]:
        """
        Get user's selected resource types from MongoDB.
        Returns None if not configured yet.
        """
        try:
            config = await self.db_manager.find_document(
                self.collection_name,
                {
                    'project_name': project_name,
                    'cloud_platform': cloud_platform.lower(),
                    'account_id': account_id
                }
            )

            if config:
                return config.get('selected_resource_types', [])

            return None

        except Exception as e:
            logger.error(f"Failed to get selected resource types: {str(e)}")
            return None

    async def save_selected_resource_types(
        self,
        project_name: str,
        cloud_platform: str,
        account_id: str,
        selected_resource_types: List[str]
    ) -> Tuple[bool, str]:
        """
        Save user's selected resource types to MongoDB.
        """
        try:
            available_types = self.get_available_resource_types(cloud_platform)

            if not available_types:
                return False, f"No resource types available for platform: {cloud_platform}"

            invalid_types = [rt for rt in selected_resource_types if rt not in available_types]
            if invalid_types:
                return False, f"Invalid resource types: {', '.join(invalid_types)}"

            filter_query = {
                'project_name': project_name,
                'cloud_platform': cloud_platform.lower(),
                'account_id': account_id
            }

            update_data = {
                'project_name': project_name,
                'cloud_platform': cloud_platform.lower(),
                'account_id': account_id,
                'selected_resource_types': selected_resource_types,
                'updated_at': datetime.utcnow().isoformat()
            }

            existing = await self.db_manager.find_document(self.collection_name, filter_query)

            if existing:
                await self.db_manager.update_document(
                    self.collection_name,
                    filter_query,
                    update_data
                )
            else:
                update_data['created_at'] = datetime.utcnow().isoformat()
                await self.db_manager.insert_document(self.collection_name, update_data)

            logger.info(f"Saved discovery config for {project_name}/{cloud_platform}/{account_id}")
            return True, "Discovery configuration saved successfully"

        except Exception as e:
            logger.error(f"Failed to save selected resource types: {str(e)}")
            return False, f"Failed to save configuration: {str(e)}"

    # ==================== Query Building ====================

    async def build_discovery_query(
        self,
        cloud_platform: str,
        project_name: str = None,
        account_id: str = None
    ) -> str:
        """
        Build discovery query for a cloud platform.

        Rules:
        - Use real columns for region/tags/account_id to preserve plugin-provided values.
        - Use to_jsonb(table)->>'title' ONLY for title (and as a fallback id/name),
        because some tables (e.g., aws_ecs_task) don't have a 'title' column.
        - Filter out NULL/empty resource_id at the end.
        """

        if project_name and account_id:
            resource_types = await self.get_selected_resource_types(
                project_name, cloud_platform, account_id
            )
            if not resource_types:
                raise ValueError(
                    "No resource types configured for discovery. "
                    "Please configure resource types before running discovery."
                )
        else:
            available = self.get_available_resource_types(cloud_platform)
            resource_types = list(available.keys())

        if not resource_types:
            raise ValueError(f"No resource types available for platform: {cloud_platform}")

        cloud = cloud_platform.lower()
        if cloud == "aws":
            acct_col = "account_id"
            region_col = "region"

            def title_json_expr(rt): return (
                f"COALESCE("
                f"  to_jsonb({rt})->>'title',"
                f"  to_jsonb({rt})->>'name',"
                f"  to_jsonb({rt})->>'arn',"
                f"  to_jsonb({rt})->>'id'"
                f")"
            )
            tags_expr = "COALESCE(tags::text, '{}')"
        elif cloud == "azure":
            acct_col = "subscription_id"
            region_col = "region"

            def title_json_expr(rt): return (
                f"COALESCE("
                f"  to_jsonb({rt})->>'title',"
                f"  to_jsonb({rt})->>'name',"
                f"  to_jsonb({rt})->>'id'"
                f")"
            )
            tags_expr = "COALESCE(tags::text, '{}')"
        elif cloud == "gcp":
            acct_col = "project"
            region_col = "location"

            def title_json_expr(rt): return (
                f"COALESCE("
                f"  to_jsonb({rt})->>'title',"
                f"  to_jsonb({rt})->>'name',"
                f"  to_jsonb({rt})->>'id'"
                f")"
            )
            tags_expr = "COALESCE(tags::text, '{}')"
        else:
            raise ValueError(f"Unsupported cloud platform: {cloud_platform}")

        union_parts = []
        for rt in resource_types:
            if cloud == "azure":
                region_select = f"COALESCE({region_col}, location, 'global') AS region"
            else:
                region_select = f"COALESCE({region_col}, 'global') AS region"

            select_query = f"""
            (
            SELECT
                '{rt}' AS resource_type,
                {title_json_expr(rt)} AS resource_id,
                {title_json_expr(rt)} AS resource_name,
                {region_select},
                {tags_expr} AS tags,
                {acct_col} AS account_id
            FROM {rt}
            )
            """.strip()

            union_parts.append(select_query)

        full_query = (
            "SELECT resource_type, resource_id, resource_name, region, tags, account_id\n"
            "FROM (\n  " + "\n  UNION ALL\n  ".join(union_parts) + "\n) q\n"
            "WHERE resource_id IS NOT NULL AND resource_id <> ''"
        )

        logger.debug(f"Built discovery query for {cloud_platform} with {len(resource_types)} resource types")
        return full_query

    def build_cost_query(self, cloud_platform: str) -> str:
        """
        Build cost discovery query for a cloud platform.
        Returns SQL string directly (no JSON encoding needed).
        """
        query = None

        if cloud_platform.lower() == 'aws':
            query = """
            SELECT
                service,
                SUM(unblended_cost_amount) as total_cost,
                period_start,
                period_end
            FROM aws_cost_by_service_monthly
            WHERE period_start >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY service, period_start, period_end
            ORDER BY total_cost DESC
            """

        elif cloud_platform.lower() == 'azure':
            query = """
            SELECT
                service_name as service,
                SUM(cost) as total_cost,
                usage_start as period_start,
                usage_end as period_end
            FROM azure_consumption_usage
            WHERE usage_start >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY service_name, usage_start, usage_end
            ORDER BY total_cost DESC
            """

        elif cloud_platform.lower() == 'gcp':
            query = """
            SELECT
                service_description as service,
                SUM(cost) as total_cost,
                usage_start_time as period_start,
                usage_end_time as period_end
            FROM gcp_billing_budget
            WHERE usage_start_time >= CURRENT_TIMESTAMP - INTERVAL '30 days'
            GROUP BY service_description, usage_start_time, usage_end_time
            ORDER BY total_cost DESC
            """
        else:
            raise ValueError(f"Cost query not supported for: {cloud_platform}")

        return query
