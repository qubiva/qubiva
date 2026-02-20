class ProjectResourceLocator:
    def __init__(self, project_manager):
        self.project_manager = project_manager

    async def locate_resource(self, project_name: str, resource_type: str, resource_name: str = None, cloud_platform: str = None):
        if resource_type == 'cloud_accounts':
            # Now passing the `cloud_platform` to get_cloud_account_details
            return await self.project_manager.get_cloud_account_details(project_name, cloud_platform, account_id=resource_name)

        elif resource_type == 'github_repos':
            return await self.project_manager.get_github_repo_details(project_name, resource_name)

        elif resource_type == 'workspaces':
            return await self.project_manager.get_workspace_details(project_name, resource_name)

        # Extend this for other types of resources as needed
        return False, "Invalid resource type"

    async def validate_project(self, project_name: str):
        """Check if a project with the given name exists."""
        success, project_details = await self.project_manager.get_project_details(project_name)
        if not success:
            return False, f"Project '{project_name}' not found"
        return True, project_details

    async def validate_resource_path(self, project_name: str, resource_type: str, resource_name: str, cloud_platform: str = None):
        # Validate the specific resource path within a project
        return await self.locate_resource(project_name, resource_type, resource_name, cloud_platform)

    def extract_resource_from_url(self, url_path: str, project_name: str):
        # Handle Cloud Accounts
        if f"/dashboard/projects/{project_name}/cloud_accounts/" in url_path:
            parts = url_path.split(f"/dashboard/projects/{project_name}/cloud_accounts/")[1].split('/')
            if len(parts) >= 2:
                cloud_platform, resource_name = parts[0], parts[1]
                remainder_url = '/'.join(parts[2:])  # Get the rest of the URL after the resource name
                return "cloud_accounts", resource_name, cloud_platform, remainder_url

        # Handle Git Repositories
        elif f"/dashboard/projects/{project_name}/git_repos/" in url_path:
            parts = url_path.split(f"/dashboard/projects/{project_name}/git_repos/")[1].split('/')
            if len(parts) >= 1:
                resource_name = parts[0]
                remainder_url = '/'.join(parts[1:])  # Get the rest of the URL after the resource name
                return "github_repos", resource_name, None, remainder_url

        # Handle Workspaces
        elif f"/dashboard/projects/{project_name}/workspaces/" in url_path:
            parts = url_path.split(f"/dashboard/projects/{project_name}/workspaces/")[1].split('/')
            if len(parts) >= 1:
                resource_name = parts[0]
                remainder_url = '/'.join(parts[1:])  # Get the rest of the URL after the resource name
                return "workspaces", resource_name, None, remainder_url

        # Add more cases for additional resources here...

        return None, None, None, None  # Default case if no known resource is found
