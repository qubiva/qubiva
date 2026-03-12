from typing import Dict, List, Any
from datetime import datetime
import logging

from app.runner_pool import RunnerPoolManager

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class StatsProvider:
    def __init__(self, project_manager, tasks_manager, cloud_alerts_manager, scheduler, request_tracker=None, session_manager=None):
        self.project_manager = project_manager
        self.tasks_manager = tasks_manager
        self.cloud_alerts_manager = cloud_alerts_manager
        self.scheduler = scheduler
        self.request_tracker = request_tracker
        self.session_manager = session_manager
        self.inactive_states = {'done', 'cancelled'}  # States to exclude from active tasks

    def _get_latest_timestamp(self, project: Dict[str, Any]) -> datetime:
        """Compute the latest timestamp for a project and its sub-entities."""
        timestamps = []

        # Add project-level timestamps
        timestamps.append(self._parse_timestamp(project.get('created_at')))
        timestamps.append(self._parse_timestamp(project.get('updated_at')))

        # Add timestamps from sub-entities - INCLUDING credentials now
        for sub_entity in ['credentials', 'cloud_accounts', 'workspaces', 'github_repos']:
            for item in project.get(sub_entity, []):
                timestamps.append(self._parse_timestamp(item.get('updated_at')))
                timestamps.append(self._parse_timestamp(item.get('created_at')))

        # Return the latest valid timestamp, defaulting to the earliest possible time
        return max(filter(None, timestamps), default=datetime.min)

    def sort_projects(self, projects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort projects based on the latest update timestamp."""
        return sorted(
            projects,
            key=self._get_latest_timestamp,
            reverse=True
        )

    async def get_user_dashboard_stats(self, username: str) -> Dict[str, Any]:
        # Check if user exists
        user_exists, user = await self.project_manager.user_exists(username)
        if not user_exists:
            raise ValueError(f"User {username} does not exist.")

        # Get org roles
        org_roles = user.get('org_roles', [])

        # Get project details
        success, project_details = await self.project_manager.get_project_details_for_projects(
            username, project_names=None, is_org_user=bool(org_roles)
        )
        if not success:
            raise ValueError("Failed to fetch project details")

        project_details_map = {}

        # Process each project
        for project_name, project_info in project_details.items():
            # Fetch user roles for the project
            user_roles = []
            result = await self.project_manager.get_user_roles_by_project(username, project_name)
            if isinstance(result, tuple):
                success_user_roles, user_roles = result
                if not success_user_roles:
                    user_roles = []

            # Fetch tasks for the project
            tasks = []
            result = await self.tasks_manager.get_all_tasks(project_name)
            if isinstance(result, tuple):
                success_tasks, tasks = result
                if not success_tasks:
                    tasks = []

            # Fetch credentials for the project
            credentials = []
            try:
                result = await self.project_manager.get_credentials_by_project(project_name)
                if isinstance(result, tuple):
                    success_credentials, credentials = result
                    if not success_credentials:
                        credentials = []
            except Exception as e:
                logger.error(f"Error fetching credentials for {project_name}: {str(e)}")
                credentials = []

            # Fetch cloud accounts for the project
            cloud_accounts = []
            result = await self.project_manager.get_cloud_accounts_by_project_name(project_name)
            if isinstance(result, tuple):
                success_cloud_accounts, cloud_accounts = result
                if not success_cloud_accounts:
                    cloud_accounts = []

            # Fetch workspaces for the project
            workspace_list = []
            result = await self.project_manager.list_workspaces(project_name)
            if isinstance(result, tuple):
                success_workspaces, workspace_list = result
                if not success_workspaces:
                    workspace_list = []

            # Fetch GitHub repos for the project
            github_repos = []
            try:
                result = await self.project_manager.get_github_repos_by_project(project_name)
                if isinstance(result, tuple):
                    success_github_repos, github_repos = result
                    if not success_github_repos:
                        github_repos = []
                elif isinstance(result, list):
                    github_repos = result
            except Exception:
                github_repos = []

            # Combine project and org roles
            roles = list(set(user_roles or []) | set(org_roles))

            # Prepare project stats
            project_details_map[project_name] = {
                'project_name': project_name,
                'created_at': self._get_safe_timestamp(project_info, 'created_at'),
                'updated_at': self._get_safe_timestamp(project_info, 'updated_at'),
                'roles': roles,
                'tasks': self._categorize_tasks(tasks, username, include_title=True),
                'credentials': [
                    {
                        'credential_name': cred['credential_name'],
                        'credential_type': cred['credential_type'],
                        'created_at': self._get_safe_timestamp(cred, 'created_at'),
                        'updated_at': self._get_safe_timestamp(cred, 'updated_at')
                    } for cred in credentials
                ],
                'cloud_accounts': [
                    {
                        'cloud_platform': account['cloud_platform'],
                        'account_id': account['account_id'],
                        'created_at': self._get_safe_timestamp(account, 'created_at'),
                        'updated_at': self._get_safe_timestamp(account, 'updated_at')
                    } for account in cloud_accounts
                ],
                'workspaces': [
                    {
                        'name': workspace['name'],
                        'created_at': self._get_safe_timestamp(workspace, 'created_at'),
                        'updated_at': self._get_safe_timestamp(workspace, 'updated_at')
                    } for workspace in workspace_list
                ],
                'github_repos': [
                    {
                        'repo_name': repo['repo_name'],
                        'repo_url': repo['repo_url'],
                        'created_at': self._get_safe_timestamp(repo, 'created_at'),
                        'updated_at': self._get_safe_timestamp(repo, 'updated_at')
                    } for repo in github_repos
                ]
            }

        # Convert project details to a list and sort them
        sorted_projects = self.sort_projects(list(project_details_map.values()))

        # Print sorted projects for debugging
        for project in sorted_projects:
            latest_timestamp = self._get_latest_timestamp(project)
            print(f"Project: {project['project_name']}, Latest Timestamp: {latest_timestamp}")

        # Return the sorted response
        return {'projects': sorted_projects}

    def _categorize_tasks(self, tasks: List[Dict[str, Any]], username: str, include_title: bool = False) -> Dict[str, List[Any]]:
        """Categorize tasks by status, excluding inactive states."""
        task_stats = {status: [] for status in ["todo", "in_progress", "blocked"]}
        for task in tasks:
            status = task.get('status')
            if status not in self.inactive_states and task.get('assignedTo') == username:
                if status in task_stats:
                    if include_title:
                        task_stats[status].append({
                            'id': task['id'],
                            'title': task.get('title', '')
                        })
                    else:
                        task_stats[status].append(task['id'])
        return task_stats

    def _get_safe_timestamp(self, data: Dict[str, Any], key: str) -> str:
        """Safely retrieve a timestamp or default to 'N/A'."""
        return data.get(key, 'N/A')

    def _parse_timestamp(self, timestamp: Any) -> datetime:
        """Parse a timestamp string or return datetime object as-is, ignoring 'N/A'."""
        if isinstance(timestamp, datetime):
            return timestamp
        if timestamp == 'N/A':
            return None
        if isinstance(timestamp, str):
            try:
                return datetime.fromisoformat(timestamp)
            except ValueError:
                return None
        return None

    async def get_project_overview(self, project_name: str, username: str) -> Dict[str, Any]:
        """
        Get comprehensive overview of a project including all its components and features.

        Args:
            project_name: Name of the project to analyze
            username: Username requesting the overview

        Returns:
            Dictionary containing project overview data
        """
        try:
            # Get basic project details
            success, project_details = await self.project_manager.get_project_details(project_name)
            if not success:
                raise ValueError(f"Failed to get project details: {project_details}")

            # Get user roles for this project
            user_roles_success, user_roles = await self.project_manager.get_user_roles_by_project(username, project_name)

            # Check if user exists and has org roles
            user_exists, user = await self.project_manager.user_exists(username)
            org_roles = user.get('org_roles', []) if user_exists else []

            # Combine project and org roles
            combined_roles = list(set(user_roles if user_roles_success else []).union(set(org_roles)))

            # Initialize response structure
            overview = {
                "project_info": {
                    "name": project_name,
                    "description": project_details.get("description", "No description available"),
                    "created_at": self._get_safe_timestamp(project_details, 'created_at'),
                    "updated_at": self._get_safe_timestamp(project_details, 'updated_at'),
                    "user_roles": combined_roles
                },
                "resources": {
                    "credentials": [],
                    "cloud_accounts": [],
                    "workspaces": [],
                    "github_repos": []
                }
            }

            # Get credentials
            try:
                success, credentials = await self.project_manager.get_credentials_by_project(project_name)
                if success and credentials:
                    overview["resources"]["credentials"] = [
                        {
                            "credential_name": cred.get("credential_name"),
                            "credential_type": cred.get("credential_type"),
                            "created_at": self._get_safe_timestamp(cred, 'created_at'),
                            "updated_at": self._get_safe_timestamp(cred, 'updated_at')
                        }
                        for cred in credentials
                    ]
            except Exception as e:
                logger.error(f"Error fetching credentials for {project_name}: {str(e)}")
                # Continue without credentials if there's an error

            # Get cloud accounts with detailed information
            success, cloud_accounts = await self.project_manager.get_cloud_accounts_by_project_name(project_name)
            if success:
                for account in cloud_accounts:
                    cloud_account_info = {
                        "platform": account.get("cloud_platform", "unknown").lower(),
                        "account_id": account.get("account_id", "unknown"),
                        "created_at": self._get_safe_timestamp(account, 'created_at'),
                        "updated_at": self._get_safe_timestamp(account, 'updated_at'),
                        "metrics": {}
                    }

                    # Get alerts for this account
                    alerts_stats = await self.cloud_alerts_manager.get_alert_stats(
                        project_name=project_name,
                        account_id=account["account_id"]
                    )
                    cloud_account_info["metrics"]["alerts"] = {
                        "open_count": alerts_stats.get("open", 0)
                    }

                    # Get scheduled runs for this account
                    schedules = await self.scheduler.list_schedules(
                        project_name,
                        filters={"payload.cloud_account": account["account_id"]}
                    )
                    cloud_account_info["metrics"]["scheduled_runs"] = {
                        "total_count": len(schedules),
                        "active_count": len([s for s in schedules if s.get("status") == "enabled"])
                    }

                    overview["resources"]["cloud_accounts"].append(cloud_account_info)

            # Get workspaces
            success, workspaces = await self.project_manager.list_workspaces(project_name)
            if success:
                overview["resources"]["workspaces"] = [
                    {
                        "name": ws["name"],
                        "created_at": self._get_safe_timestamp(ws, 'created_at'),
                        "updated_at": self._get_safe_timestamp(ws, 'updated_at')
                    }
                    for ws in workspaces
                ]

            # Get GitHub repositories
            success, github_repos = await self.project_manager.get_github_repos_by_project(project_name)
            if success:
                overview["resources"]["github_repos"] = [
                    {
                        "name": repo["repo_name"],
                        "url": repo["repo_url"],
                        "created_at": self._get_safe_timestamp(repo, 'created_at'),
                        "updated_at": self._get_safe_timestamp(repo, 'updated_at')
                    }
                    for repo in github_repos
                ]

            # Get tasks
            success, tasks = await self.tasks_manager.get_all_tasks(project_name)
            if success:
                overview["tasks"] = self._categorize_tasks(tasks, username, include_title=True)

            # Get runner pool status
            pool_summary = RunnerPoolManager.get_pool_summary()
            if self.session_manager:
                pool_summary.update(self.session_manager.get_pool_summary())
            overview["runners"] = {"pool": pool_summary}

            return overview

        except Exception as e:
            logger.error(f"Error getting project overview for {project_name}: {str(e)}")
            raise

    def _count_by_platform(self, cloud_accounts: List[Dict]) -> Dict[str, int]:
        """Helper method to count cloud accounts by platform"""
        platform_counts = {"aws": 0, "azure": 0, "gcp": 0}
        for account in cloud_accounts:
            platform = account.get("cloud_platform", "").lower()
            if platform in platform_counts:
                platform_counts[platform] += 1
        return platform_counts
