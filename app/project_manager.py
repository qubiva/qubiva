"""
ProjectManager facade -- thin delegation layer over domain-specific sub-managers.

All public methods are preserved so that existing callers (routes, deps, etc.)
continue to work unchanged via ``project_manager.method_name()``.
"""

import logging
import os
import re
from datetime import datetime
from app.app_config_manager import ConfigManager
from app.managers import (
    UserManager,
    CredentialManager,
    GitRepoManager,
    GitHubAppManager,
    SSOConfigManager,
    ProjectCrudManager,
    CloudAccountManager,
    WorkspaceManager,
)

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class ProjectManager:
    def __init__(self, db_manager, kms_manager, email_service, rbac, scheduler):
        self.db_manager = db_manager
        self.kms_manager = kms_manager
        self.email_service = email_service
        self.rbac = rbac
        self.scheduler = scheduler
        self._domain_env = os.getenv("DOMAIN")

        # Build sub-managers
        self._user_mgr = UserManager(db_manager, kms_manager, email_service, rbac)
        self._credential_mgr = CredentialManager(db_manager, kms_manager)
        self._git_repo_mgr = GitRepoManager(db_manager, kms_manager)
        self._github_app_mgr = GitHubAppManager(db_manager, kms_manager)
        self._sso_config_mgr = SSOConfigManager(db_manager, kms_manager, rbac)
        self._cloud_account_mgr = CloudAccountManager(db_manager, kms_manager, self._credential_mgr)
        self._workspace_mgr = WorkspaceManager(db_manager, kms_manager, self._git_repo_mgr)
        self._project_crud_mgr = ProjectCrudManager(db_manager, kms_manager, rbac, scheduler, self._user_mgr)

    # ------------------------------------------------------------------
    # Shared utility methods (also on ManagerBase, kept here for compat)
    # ------------------------------------------------------------------

    @staticmethod
    def _audit_create(acting_user: str = None) -> dict:
        """Return audit fields for a new document."""
        now = datetime.utcnow()
        fields = {"created_at": now, "updated_at": now}
        if acting_user:
            fields["created_by"] = acting_user
            fields["updated_by"] = acting_user
        return fields

    @staticmethod
    def _audit_update(acting_user: str = None) -> dict:
        """Return audit fields for a document update."""
        fields = {"updated_at": datetime.utcnow()}
        if acting_user:
            fields["updated_by"] = acting_user
        return fields

    @property
    def domain(self):
        """Get app base URL from config, falling back to DOMAIN env var."""
        url = ConfigManager.get_config('app', 'base_url')
        if url:
            return url.rstrip('/')
        if self._domain_env:
            return f"https://{self._domain_env}"
        return None

    def encrypt_data(self, data: str) -> str:
        return self.kms_manager.encrypt(data)

    def decrypt_data(self, encrypted_data: str = None) -> str:
        if encrypted_data is None:
            logger.error("No encrypted data provided for decryption.")
            return "DECRYPTION_FAILED"
        try:
            logger.debug(encrypted_data)
            return self.kms_manager.decrypt(encrypted_data=encrypted_data)
        except Exception as e:
            logger.error(f"Decryption failed for data: {str(e)}")
            return "DECRYPTION_FAILED"

    # ------------------------------------------------------------------
    # User management delegation
    # ------------------------------------------------------------------

    async def create_users(self, *args, **kwargs):
        return await self._user_mgr.create_users(*args, **kwargs)

    async def modify_users_org_roles(self, *args, **kwargs):
        return await self._user_mgr.modify_users_org_roles(*args, **kwargs)

    async def delete_users(self, *args, **kwargs):
        return await self._user_mgr.delete_users(*args, **kwargs)

    async def create_password_reset_token(self, *args, **kwargs):
        return await self._user_mgr.create_password_reset_token(*args, **kwargs)

    async def send_password_reset_email(self, *args, **kwargs):
        return await self._user_mgr.send_password_reset_email(*args, **kwargs)

    async def reset_password(self, *args, **kwargs):
        return await self._user_mgr.reset_password(*args, **kwargs)

    async def user_exists(self, *args, **kwargs):
        return await self._user_mgr.user_exists(*args, **kwargs)

    async def deactivate_user(self, *args, **kwargs):
        return await self._user_mgr.deactivate_user(*args, **kwargs)

    async def reactivate_user(self, *args, **kwargs):
        return await self._user_mgr.reactivate_user(*args, **kwargs)

    # ------------------------------------------------------------------
    # Project CRUD delegation
    # ------------------------------------------------------------------

    async def get_project_details(self, *args, **kwargs):
        return await self._project_crud_mgr.get_project_details(*args, **kwargs)

    async def get_project(self, *args, **kwargs):
        return await self._project_crud_mgr.get_project(*args, **kwargs)

    async def create_project(self, *args, **kwargs):
        return await self._project_crud_mgr.create_project(*args, **kwargs)

    async def delete_project(self, *args, **kwargs):
        return await self._project_crud_mgr.delete_project(*args, **kwargs)

    async def update_project(self, *args, **kwargs):
        return await self._project_crud_mgr.update_project(*args, **kwargs)

    async def remove_project_from_user(self, *args, **kwargs):
        return await self._project_crud_mgr.remove_project_from_user(*args, **kwargs)

    async def add_project_to_user(self, *args, **kwargs):
        return await self._project_crud_mgr.add_project_to_user(*args, **kwargs)

    async def add_member_to_project(self, *args, **kwargs):
        return await self._project_crud_mgr.add_member_to_project(*args, **kwargs)

    async def add_members_to_project(self, *args, **kwargs):
        return await self._project_crud_mgr.add_members_to_project(*args, **kwargs)

    async def remove_member_from_project(self, *args, **kwargs):
        return await self._project_crud_mgr.remove_member_from_project(*args, **kwargs)

    async def remove_members_from_project(self, *args, **kwargs):
        return await self._project_crud_mgr.remove_members_from_project(*args, **kwargs)

    async def get_project_details_for_projects(self, *args, **kwargs):
        return await self._project_crud_mgr.get_project_details_for_projects(*args, **kwargs)

    async def get_all_projects(self, *args, **kwargs):
        return await self._project_crud_mgr.get_all_projects(*args, **kwargs)

    async def get_user_roles_by_project(self, *args, **kwargs):
        return await self._project_crud_mgr.get_user_roles_by_project(*args, **kwargs)

    async def get_project_members(self, *args, **kwargs):
        return await self._project_crud_mgr.get_project_members(*args, **kwargs)

    async def search_projects(self, *args, **kwargs):
        return await self._project_crud_mgr.search_projects(*args, **kwargs)

    # ------------------------------------------------------------------
    # Cloud account delegation
    # ------------------------------------------------------------------

    async def add_cloud_account_to_project(self, *args, **kwargs):
        return await self._cloud_account_mgr.add_cloud_account_to_project(*args, **kwargs)

    async def get_cloud_accounts_by_project_name(self, *args, **kwargs):
        return await self._cloud_account_mgr.get_cloud_accounts_by_project_name(*args, **kwargs)

    async def update_project_cloud_account(self, *args, **kwargs):
        return await self._cloud_account_mgr.update_project_cloud_account(*args, **kwargs)

    async def delete_cloud_account_from_project(self, *args, **kwargs):
        return await self._cloud_account_mgr.delete_cloud_account_from_project(*args, **kwargs)

    async def get_cloud_account_details(self, *args, **kwargs):
        return await self._cloud_account_mgr.get_cloud_account_details(*args, **kwargs)

    async def search_cloud_accounts(self, *args, **kwargs):
        return await self._cloud_account_mgr.search_cloud_accounts(*args, **kwargs)

    # ------------------------------------------------------------------
    # Git repo delegation
    # ------------------------------------------------------------------

    async def add_github_repo_to_project(self, *args, **kwargs):
        return await self._git_repo_mgr.add_github_repo_to_project(*args, **kwargs)

    async def get_github_repos_by_project(self, *args, **kwargs):
        return await self._git_repo_mgr.get_github_repos_by_project(*args, **kwargs)

    async def update_github_repo(self, *args, **kwargs):
        return await self._git_repo_mgr.update_github_repo(*args, **kwargs)

    async def delete_github_repo(self, *args, **kwargs):
        return await self._git_repo_mgr.delete_github_repo(*args, **kwargs)

    async def get_github_repo_details(self, *args, **kwargs):
        return await self._git_repo_mgr.get_github_repo_details(*args, **kwargs)

    async def search_github_repos(self, *args, **kwargs):
        return await self._git_repo_mgr.search_github_repos(*args, **kwargs)

    # ------------------------------------------------------------------
    # Workspace delegation
    # ------------------------------------------------------------------

    async def create_workspace(self, *args, **kwargs):
        return await self._workspace_mgr.create_workspace(*args, **kwargs)

    async def delete_workspace_from_project(self, *args, **kwargs):
        return await self._workspace_mgr.delete_workspace_from_project(*args, **kwargs)

    async def update_workspace(self, *args, **kwargs):
        return await self._workspace_mgr.update_workspace(*args, **kwargs)

    async def get_workspace_details(self, *args, **kwargs):
        return await self._workspace_mgr.get_workspace_details(*args, **kwargs)

    async def list_workspaces(self, *args, **kwargs):
        return await self._workspace_mgr.list_workspaces(*args, **kwargs)

    async def set_workspace_state(self, *args, **kwargs):
        return await self._workspace_mgr.set_workspace_state(*args, **kwargs)

    async def is_workspace_locked(self, *args, **kwargs):
        return await self._workspace_mgr.is_workspace_locked(*args, **kwargs)

    # ------------------------------------------------------------------
    # Credential delegation
    # ------------------------------------------------------------------

    async def _resolve_credential_reference(self, *args, **kwargs):
        return await self._credential_mgr._resolve_credential_reference(*args, **kwargs)

    async def create_credential(self, *args, **kwargs):
        return await self._credential_mgr.create_credential(*args, **kwargs)

    async def get_credentials_by_project(self, *args, **kwargs):
        return await self._credential_mgr.get_credentials_by_project(*args, **kwargs)

    async def get_credential_details(self, *args, **kwargs):
        return await self._credential_mgr.get_credential_details(*args, **kwargs)

    async def update_credential(self, *args, **kwargs):
        return await self._credential_mgr.update_credential(*args, **kwargs)

    async def delete_credential(self, *args, **kwargs):
        return await self._credential_mgr.delete_credential(*args, **kwargs)

    # ------------------------------------------------------------------
    # GitHub App delegation
    # ------------------------------------------------------------------

    async def setup_github_app(self, *args, **kwargs):
        return await self._github_app_mgr.setup_github_app(*args, **kwargs)

    async def store_installation_mapping(self, *args, **kwargs):
        return await self._github_app_mgr.store_installation_mapping(*args, **kwargs)

    async def get_github_app_client(self, *args, **kwargs):
        return await self._github_app_mgr.get_github_app_client(*args, **kwargs)

    async def github_app_api_call(self, *args, **kwargs):
        return await self._github_app_mgr.github_app_api_call(*args, **kwargs)

    async def get_github_app_status(self, *args, **kwargs):
        return await self._github_app_mgr.get_github_app_status(*args, **kwargs)

    async def get_installation_token_for_repo(self, *args, **kwargs):
        return await self._github_app_mgr.get_installation_token_for_repo(*args, **kwargs)

    async def search_github_app_repos_for_picker(self, *args, **kwargs):
        return await self._github_app_mgr.search_github_app_repos_for_picker(*args, **kwargs)

    async def get_org_name_from_installation(self, *args, **kwargs):
        return await self._github_app_mgr.get_org_name_from_installation(*args, **kwargs)

    async def delete_github_app_configuration(self, *args, **kwargs):
        return await self._github_app_mgr.delete_github_app_configuration(*args, **kwargs)

    async def validate_installation_belongs_to_app(self, *args, **kwargs):
        return await self._github_app_mgr.validate_installation_belongs_to_app(*args, **kwargs)

    # ------------------------------------------------------------------
    # SSO config delegation
    # ------------------------------------------------------------------

    async def get_sso_config(self, *args, **kwargs):
        return await self._sso_config_mgr.get_sso_config(*args, **kwargs)

    async def update_sso_config(self, *args, **kwargs):
        return await self._sso_config_mgr.update_sso_config(*args, **kwargs)

    async def _parse_idp_metadata(self, *args, **kwargs):
        return await self._sso_config_mgr._parse_idp_metadata(*args, **kwargs)

    async def delete_sso_config(self, *args, **kwargs):
        return await self._sso_config_mgr.delete_sso_config(*args, **kwargs)

    async def update_sso_user_roles_on_login(self, *args, **kwargs):
        return await self._sso_config_mgr.update_sso_user_roles_on_login(*args, **kwargs)

    def _determine_org_roles_from_groups(self, *args, **kwargs):
        return self._sso_config_mgr._determine_org_roles_from_groups(*args, **kwargs)

    # ------------------------------------------------------------------
    # Orchestration methods (cross-domain, kept on facade)
    # ------------------------------------------------------------------

    async def get_terraform_run_details(self, project_name: str, workspace_name: str):
        try:
            # Fetch project details
            project_success, project_data = await self.get_project_details(project_name)
            if not project_success:
                return False, f"Failed to fetch project details: {project_data}"

            # Fetch workspace details
            workspace_success, workspace_data = await self.get_workspace_details(project_name, workspace_name)
            if not workspace_success:
                return False, f"Failed to fetch workspace details: {workspace_data}"

            cloud_account_id = workspace_data.get('cloud_account')
            cloud_platform = workspace_data.get('cloud_platform')
            if not cloud_account_id or not cloud_platform:
                return False, f"Workspace '{workspace_name}' does not have cloud account configured"

            # Get github_repo_name from workspace
            github_repo_name = workspace_data.get('github_repo_name')
            if not github_repo_name:
                return False, f"No GitHub repository associated with workspace '{workspace_name}'"

            # Initialize consolidated data
            consolidated_data = {
                "variables": {},
                "secrets": {},
                "backend_config": {},
                "github_repo": {}
            }

            # Add project-level variables and secrets
            consolidated_data["variables"].update(project_data.get("variables", {}))
            consolidated_data["secrets"].update(project_data.get("secrets", {}))

            cloud_success, cloud_data = await self.get_cloud_account_details(project_name, cloud_platform, cloud_account_id)
            if not cloud_success:
                return False, f"Failed to fetch cloud account details: {cloud_data}"

            # Override with cloud account variables and secrets
            consolidated_data["variables"].update(cloud_data.get("variables", {}))
            consolidated_data["secrets"].update(cloud_data.get("secrets", {}))

            consolidated_data["cloud_platform"] = cloud_platform
            consolidated_data["cloud_account"] = cloud_account_id

            # Override with workspace-level variables and secrets
            consolidated_data["variables"].update(workspace_data.get("variables", {}))
            consolidated_data["secrets"].update(workspace_data.get("secrets", {}))

            # Add backend configuration
            backend_type = (workspace_data.get("tf_backend_type") or os.getenv('TF_BACKEND_TYPE', 'kubernetes')).lower()
            backend_statefile_path = workspace_data.get("tf_backend_statefile_path", "")

            # Backward-compatible fallback for existing workspaces
            if not backend_statefile_path:
                if backend_type == 'kubernetes':
                    raw_key = f"{project_name}-{workspace_name}"
                    backend_statefile_path = re.sub(r'[^a-zA-Z0-9-]', '-', raw_key).strip('-').lower()
                else:
                    backend_statefile_path = f"{project_name}/{workspace_name}.tf"

            consolidated_data["backend_type"] = backend_type
            consolidated_data["backend_config"] = {
                "backend_statefile_path": backend_statefile_path
            }

            # Add Terraform version
            consolidated_data["terraform_version"] = workspace_data.get("terraform_version")

            # Fetch and add GitHub repo details
            github_success, github_data = await self.get_github_repo_details(project_name, github_repo_name)
            if not github_success:
                return False, f"Failed to fetch GitHub repo details: {github_data}"

            consolidated_data["github_repo"] = {
                "repo_url": github_data.get("repo_url"),
                "terraform_config_path": github_data.get("terraform_config_path", ""),
                "branch": github_data.get("branch"),
                "policy_governance_path": github_data.get("policy_governance_path", ""),
                "token": github_data.get("token", "")
            }

            org_success, org_policy_repo = await self.get_org_policy_repo()
            if org_success and org_policy_repo:
                consolidated_data["org_policy_repo"] = org_policy_repo
            else:
                consolidated_data["org_policy_repo"] = None

            logger.info(f"Successfully consolidated Terraform run details for project '{project_name}', workspace '{workspace_name}'")
            return True, consolidated_data

        except Exception as e:
            logger.error(f"Failed to get Terraform run details for project '{project_name}', workspace '{workspace_name}': {str(e)}")
            return False, f"Failed to get Terraform run details: {str(e)}"

    async def get_github_token_for_container_run(self, repo_url: str, repo_details: dict = None):
        """Get GitHub token for container runs - PAT first, GitHub App fallback, None for public repos"""
        try:
            # Try PAT first (user's explicit choice)
            if repo_details and repo_details.get("token"):
                decrypted_pat = self.decrypt_data(repo_details["token"])
                if decrypted_pat != "DECRYPTION_FAILED":
                    logger.info(f"Using PAT token for container run: {repo_url}")
                    return decrypted_pat, 'pat'
                else:
                    logger.warning(f"PAT token decryption failed for {repo_url}, falling back to GitHub App")

            # Fallback to GitHub App
            success, token_data = await self.get_installation_token_for_repo(repo_url)
            if success:
                logger.info(f"Using GitHub App token for container run: {repo_url}")
                return token_data['token'], 'github_app'
            else:
                logger.info(f"GitHub App authentication unavailable for {repo_url}: {token_data}")

            # If both PAT and GitHub App are unavailable, assume it's a public repo
            logger.info(f"No GitHub authentication available for {repo_url}, assuming public repository")
            return None, 'public'

        except Exception as e:
            logger.error(f"Failed to get GitHub token for container run: {str(e)}")
            raise

    async def get_org_policy_repo(self):
        """
        Get organization-level policy governance repository configuration.
        Returns (success, repo_data) where repo_data contains repo details or None if not configured.
        """
        try:
            org_policy = await self.db_manager.find_document('org_settings', {'setting_type': 'policy_governance'})
            if not org_policy:
                return True, None  # No org policy configured

            repo_data = org_policy.get('github_repo', {})
            if not repo_data:
                return True, None

            # Decrypt token if present
            if 'token' in repo_data and repo_data['token']:
                repo_data['token'] = self.decrypt_data(repo_data['token'])

            return True, repo_data

        except Exception as e:
            logger.error(f"Failed to get org policy repo: {str(e)}")
            return False, f"Failed to get org policy repo: {str(e)}"

    async def update_org_policy_repo(self, repo_url, branch=None, token=None, policy_path=None, conftest_version=None):
        """
        Update organization-level policy governance repository configuration.
        Creates or updates a single document in org_settings collection.
        """
        try:
            # Prepare repo data
            repo_data = {
                'repo_url': repo_url,
                'branch': branch,
                'policy_path': policy_path,
                'conftest_version': conftest_version
            }

            # Encrypt token if provided
            if token:
                repo_data['token'] = self.encrypt_data(token)

            # Prepare the document
            org_setting = {
                'setting_type': 'policy_governance',
                'github_repo': repo_data,
                'updated_at': datetime.utcnow()
            }

            # Upsert the document (update if exists, create if not)
            await self.db_manager.update_one_document(
                'org_settings',
                {'setting_type': 'policy_governance'},
                {'$set': org_setting, '$setOnInsert': {'created_at': datetime.utcnow()}},
                upsert=True
            )

            return True, "Organization policy repository updated successfully"

        except Exception as e:
            logger.error(f"Failed to update org policy repo: {str(e)}")
            return False, f"Failed to update org policy repo: {str(e)}"
