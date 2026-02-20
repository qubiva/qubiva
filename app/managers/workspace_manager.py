import logging
import os
import re
from app.managers.base import ManagerBase

logger = logging.getLogger('uvicorn.error')


class WorkspaceManager(ManagerBase):
    def __init__(self, db_manager, kms_manager, git_repo_manager):
        super().__init__(db_manager, kms_manager)
        self.git_repo_manager = git_repo_manager

    async def create_workspace(self, project_name: str, workspace_name: str, description: str = "", variables: dict = None, secrets: dict = None, terraform_version: str = None, github_repo_name: str = None, cloud_account: str = None, cloud_platform: str = None, acting_user: str = None):
        try:
            # Check if the project exists
            project = await self.db_manager.find_document('projects', {'project_name': project_name})
            if not project:
                return False, f"Project '{project_name}' not found"

            # Check if the workspace already exists
            existing_workspace = await self.db_manager.find_document('workspaces', {'project_name': project_name, 'name': workspace_name})
            if existing_workspace:
                return False, f"Workspace '{workspace_name}' already exists in project '{project_name}'"

            # Validate GitHub repo if provided
            if github_repo_name:
                repo_success, repo_data = await self.git_repo_manager.get_github_repo_details(project_name, github_repo_name)
                if not repo_success:
                    return False, f"GitHub repository '{github_repo_name}' not found in project '{project_name}'"

            # Determine Terraform backend state path based on configured backend type
            backend_type = os.getenv('TF_BACKEND_TYPE', 'kubernetes').lower()

            if backend_type in ['s3', 'gcs']:
                tf_state_bucket = os.getenv('TF_STATE_BUCKET')
                if not tf_state_bucket:
                    return False, "Environment variable 'TF_STATE_BUCKET' is not set."
                tf_backend = f"{tf_state_bucket}/{project_name}/{workspace_name}.tf"
            elif backend_type == 'kubernetes':
                # Kubernetes backend uses secret suffix; keep it compact and stable
                raw_key = f"{project_name}-{workspace_name}"
                tf_backend = re.sub(r'[^a-zA-Z0-9-]', '-', raw_key).strip('-').lower()
            else:
                # local/azurerm or any custom backend can still use a deterministic path key
                tf_backend = f"{project_name}/{workspace_name}.tf"

            # Prepare workspace data
            workspace_data = {
                'project_name': project_name,
                'name': workspace_name,
                'description': description,
                'variables': variables or {},
                'secrets': {},
                'tf_backend_statefile_path': tf_backend,
                'tf_backend_type': backend_type,
                'terraform_version': terraform_version,
                'github_repo_name': github_repo_name,
                'cloud_account': cloud_account,
                'cloud_platform': cloud_platform
            }
            workspace_data.update(self._audit_create(acting_user))
            logger.debug(f"Creating workspace data: {workspace_data}")

            # Encrypt secrets
            if secrets:
                for key, value in secrets.items():
                    workspace_data['secrets'][key] = self.encrypt_data(value)

            # Insert the workspace into the database
            await self.db_manager.insert_document('workspaces', workspace_data)
            return True, f"Workspace '{workspace_name}' created successfully in project '{project_name}'"
        except Exception as e:
            logger.error(f"Failed to create workspace '{workspace_name}' in project '{project_name}': {str(e)}")
            return False, f"Failed to create workspace: {str(e)}"

    async def delete_workspace_from_project(self, project_name: str, workspace_name: str, acting_user: str = None):
        try:
            # Attempt to delete the workspace from the 'workspaces' collection based on the project and workspace name
            result = await self.db_manager.delete_document(
                'workspaces',
                {'project_name': project_name, 'name': workspace_name}
            )

            # Check if the deletion was successful by looking at the result
            if result > 0:
                return True, f"Workspace '{workspace_name}' deleted successfully from project '{project_name}'"
            else:
                return False, f"Workspace '{workspace_name}' not found in project '{project_name}'"

        except Exception as e:
            # Log the error and return a failure response
            logger.error(f"Failed to delete workspace '{workspace_name}' from project '{project_name}': {str(e)}")
            return False, f"Failed to delete workspace: {str(e)}"

    async def update_workspace(self, project_name: str, workspace_name: str, description: str = None, variables: dict = None, secrets: dict = None, terraform_version: str = None, github_repo_name: str = None, cloud_account: str = None, cloud_platform: str = None, acting_user: str = None):
        try:
            # Fetch the existing workspace
            workspace = await self.db_manager.find_document('workspaces', {'project_name': project_name, 'name': workspace_name})
            if not workspace:
                return False, f"Workspace '{workspace_name}' not found in project '{project_name}'"

            # Validate GitHub repo if provided
            if github_repo_name is not None and github_repo_name:
                repo_success, repo_data = await self.git_repo_manager.get_github_repo_details(project_name, github_repo_name)
                if not repo_success:
                    return False, f"GitHub repository '{github_repo_name}' not found in project '{project_name}'"

            # Update fields
            update_data = {**self._audit_update(acting_user)}
            if description is not None:
                update_data['description'] = description
            if variables is not None:
                update_data['variables'] = variables
            if secrets is not None:
                encrypted_secrets = {}
                for key, value in secrets.items():
                    encrypted_secrets[key] = self.encrypt_data(value)
                update_data['secrets'] = encrypted_secrets
            if terraform_version is not None:
                update_data['terraform_version'] = terraform_version
            if github_repo_name is not None:
                update_data['github_repo_name'] = github_repo_name
            if cloud_account is not None:
                update_data['cloud_account'] = cloud_account
            if cloud_platform is not None:
                update_data['cloud_platform'] = cloud_platform

            # Update the workspace in the database
            result = await self.db_manager.update_one_document(
                'workspaces',
                {'project_name': project_name, 'name': workspace_name},
                {'$set': update_data}
            )

            if result['modified_count'] > 0:
                return True, f"Workspace '{workspace_name}' updated successfully"
            return False, "No changes were made to the workspace"
        except Exception as e:
            logger.error(f"Failed to update workspace '{workspace_name}' in project '{project_name}': {str(e)}")
            return False, f"Failed to update workspace: {str(e)}"

    async def get_workspace_details(self, project_name: str, workspace_name: str):
        try:
            workspace = await self.db_manager.find_document('workspaces', {'project_name': project_name, 'name': workspace_name})
            if not workspace:
                return False, f"Workspace '{workspace_name}' not found in project '{project_name}'"
            logger.debug(workspace)
            # Decrypt secrets
            if 'secrets' in workspace:
                decrypted_secrets = {}
                for key, encrypted_value in workspace['secrets'].items():
                    decrypted_secrets[key] = self.decrypt_data(encrypted_value)
                workspace['secrets'] = decrypted_secrets

            if 'terraform_version' not in workspace:
                workspace['terraform_version'] = None
                logger.warning(f"terraform_version not found for workspace '{workspace_name}' in project '{project_name}'")

            return True, workspace
        except Exception as e:
            logger.error(f"Failed to get workspace details for '{workspace_name}' in project '{project_name}': {str(e)}")
            return False, f"Failed to get workspace details: {str(e)}"

    async def list_workspaces(self, project_name: str):
        try:
            workspaces = await self.db_manager.find_documents('workspaces', {'project_name': project_name})
            return True, workspaces
        except Exception as e:
            logger.error(f"Failed to list workspaces for project '{project_name}': {str(e)}")
            return False, f"Failed to list workspaces: {str(e)}"

    async def set_workspace_state(self, project_name: str, workspace_name: str, locked: bool, request_id: str = None):
        """
        Set workspace lock state. When locked=True, stores the request_id that locked it.
        When locked=False, clears the lock.
        """
        try:
            update_data = {
                'locked': locked,
                'current_run_request_id': request_id if locked else None
            }

            result = await self.db_manager.update_one_document(
                'workspaces',
                {'project_name': project_name, 'name': workspace_name},
                {'$set': update_data}
            )

            if result['matched_count'] > 0:
                action = "locked" if locked else "unlocked"
                return True, f"Workspace '{workspace_name}' {action} successfully"
            return False, f"Workspace '{workspace_name}' not found in project '{project_name}'"

        except Exception as e:
            logger.error(f"Failed to set workspace state: {str(e)}")
            return False, f"Failed to set workspace state: {str(e)}"

    async def is_workspace_locked(self, project_name: str, workspace_name: str):
        """
        Check if workspace is locked and return lock details.
        Returns (is_locked, current_run_request_id)
        """
        try:
            success, workspace = await self.get_workspace_details(project_name, workspace_name)
            if not success:
                return False, None

            is_locked = workspace.get('locked', False)
            current_run_id = workspace.get('current_run_request_id')

            return is_locked, current_run_id

        except Exception as e:
            logger.error(f"Failed to check workspace lock state: {str(e)}")
            return False, None
