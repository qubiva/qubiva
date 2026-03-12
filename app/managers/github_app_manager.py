import logging
import time
import jwt
import requests
from typing import Tuple
from datetime import datetime
from github import GithubIntegration, Auth
from app.managers.base import ManagerBase

logger = logging.getLogger('uvicorn.error')


class GitHubAppManager(ManagerBase):
    def __init__(self, db_manager, kms_manager):
        super().__init__(db_manager, kms_manager)

    async def setup_github_app(self, app_id: int, private_key_content: str):
        """One-time setup to store GitHub App credentials securely"""
        try:
            github_app_config = {
                'setting_type': 'github_app',
                'app_id': app_id,
                'private_key': self.encrypt_data(private_key_content),
                'updated_at': datetime.utcnow()
            }

            await self.db_manager.update_one_document(
                'org_settings',
                {'setting_type': 'github_app'},
                {
                    '$set': github_app_config,
                    '$setOnInsert': {'created_at': datetime.utcnow()}
                },
                upsert=True
            )

            return True, "GitHub App configured successfully"
        except Exception as e:
            logger.error(f"Failed to setup GitHub App: {str(e)}")
            return False, f"Failed to setup GitHub App: {str(e)}"

    async def store_installation_mapping(self, org_name: str, installation_id: int):
        """Store GitHub App installation ID for an organization"""
        try:
            installation_data = {
                'org_name': org_name,
                'installation_id': installation_id,
                'updated_at': datetime.utcnow()  # Remove created_at from here
            }

            await self.db_manager.update_one_document(
                'github_installations',
                {'org_name': org_name},
                {
                    '$set': installation_data,
                    '$setOnInsert': {'created_at': datetime.utcnow()}
                },
                upsert=True
            )

            return True, f"Installation mapping stored for {org_name}"
        except Exception as e:
            logger.error(f"Failed to store installation mapping: {str(e)}")
            return False, f"Failed to store installation mapping: {str(e)}"

    async def get_github_app_client(self, org_name: str):
        """Get authenticated GitHub client for organization using App authentication"""
        try:
            # Get GitHub App config
            app_config = await self.db_manager.find_document('org_settings', {'setting_type': 'github_app'})
            if not app_config:
                logger.error("GitHub App not configured")
                return None

            app_id = app_config['app_id']
            private_key = self.decrypt_data(app_config['private_key'])
            if private_key == "DECRYPTION_FAILED":
                logger.error("Failed to decrypt GitHub App private key")
                return None

            # Get installation ID for org
            installation_mapping = await self.db_manager.find_document('github_installations', {'org_name': org_name})
            if not installation_mapping:
                logger.error(f"No installation found for org: {org_name}")
                return None

            installation_id = installation_mapping['installation_id']

            # Create GitHub App authentication
            auth = Auth.AppAuth(app_id, private_key)
            integration = GithubIntegration(auth=auth)

            # Get installation access token and create client
            for installation in integration.get_installations():
                if installation.id == installation_id:
                    return installation.get_github_for_installation()

            logger.error(f"Installation {installation_id} not found for org {org_name}")
            return None

        except Exception as e:
            logger.error(f"Failed to create GitHub App client for {org_name}: {str(e)}")
            return None

    async def github_app_api_call(self, org_name: str, repo_name: str = None, operation: str = "get_repo"):
        """Make authenticated GitHub API calls using App authentication"""
        try:
            github_client = await self.get_github_app_client(org_name)
            logger.info(f"github_app_api_call called with: org_name={org_name}, repo_name={repo_name}, operation={operation}")
            if not github_client:
                return False, "Failed to authenticate with GitHub App"
            logger.info(f"GitHub client created successfully for {org_name}")
            if operation == "get_repo" and repo_name:
                repo = github_client.get_repo(f"{org_name}/{repo_name}")
                return True, {
                    'name': repo.name,
                    'full_name': repo.full_name,
                    'description': repo.description,
                    'private': repo.private,
                    'default_branch': repo.default_branch,
                    'clone_url': repo.clone_url
                }
            elif operation == "list_repos":
                try:
                    # For GitHub Apps, use installation.get_repos() to get repos the installation has access to
                    logger.info(f"Fetching installation repos for: {org_name}")

                    # Get the installation object
                    installation_mapping = await self.db_manager.find_document('github_installations', {'org_name': org_name})
                    if not installation_mapping:
                        logger.error(f"No installation found for org: {org_name}")
                        return False, f"No installation found for org: {org_name}"

                    installation_id = installation_mapping['installation_id']

                    # Get app config
                    app_config = await self.db_manager.find_document('org_settings', {'setting_type': 'github_app'})
                    if not app_config:
                        logger.error("GitHub App not configured")
                        return False, "GitHub App not configured"

                    app_id = app_config['app_id']
                    private_key = self.decrypt_data(app_config['private_key'])
                    if private_key == "DECRYPTION_FAILED":
                        logger.error("Failed to decrypt GitHub App private key")
                        return False, "Failed to decrypt GitHub App private key"

                    # Create GitHub App authentication
                    auth = Auth.AppAuth(app_id, private_key)
                    integration = GithubIntegration(auth=auth)

                    # Get installation and list its accessible repos
                    repos = []
                    for installation in integration.get_installations():
                        if installation.id == installation_id:
                            logger.info(f"Found installation {installation_id}, fetching accessible repos")
                            # This returns only repos the installation has access to
                            for repo in installation.get_repos():
                                logger.info(f"Found repo: {repo.full_name}, private={repo.private}")
                                repos.append({
                                    'name': repo.name,
                                    'full_name': repo.full_name,
                                    'private': repo.private
                                })
                            logger.info(f"Total accessible repos: {len(repos)}")
                            return True, repos

                    logger.error(f"Installation {installation_id} not found")
                    return False, f"Installation {installation_id} not found"

                except Exception as e:
                    logger.error(f"Failed to list repos: {str(e)}")
                    return False, f"Failed to list repos: {str(e)}"
            else:
                return False, "Unsupported operation"

        except Exception as e:
            logger.error(f"GitHub App API call failed: {str(e)}")
            return False, f"GitHub App API call failed: {str(e)}"

    async def get_github_app_status(self):
        """Check if GitHub App is configured and list installations"""
        try:
            app_config = await self.db_manager.find_document('org_settings', {'setting_type': 'github_app'})
            if not app_config:
                return True, {'configured': False, 'installations': []}

            installations = await self.db_manager.find_documents('github_installations', {})
            installation_list = [
                {
                    'org_name': inst['org_name'],
                    'installation_id': inst['installation_id'],
                    'created_at': inst['created_at']
                }
                for inst in installations
            ]

            return True, {
                'configured': True,
                'app_id': app_config['app_id'],
                'installations': installation_list
            }
        except Exception as e:
            logger.error(f"Failed to get GitHub App status: {str(e)}")
            return False, f"Failed to get GitHub App status: {str(e)}"

    async def get_installation_token_for_repo(self, repo_url: str):
        """Get fresh installation token for a specific repository"""
        try:
            # Extract org name from repo URL
            if "github.com/" not in repo_url:
                return False, "Invalid GitHub repository URL"

            url_parts = repo_url.replace("https://github.com/", "").replace(".git", "")
            org_name = url_parts.split("/")[0]

            # Get GitHub App client for this org
            github_client = await self.get_github_app_client(org_name)
            if not github_client:
                return False, f"No GitHub App installation found for org: {org_name}"

            # Extract the installation token
            installation_token = github_client._Github__requester._Requester__auth.token

            return True, {
                'token': installation_token,
                'expires_in': 3600,  # 1 hour
                'token_type': 'installation'
            }

        except Exception as e:
            logger.error(f"Failed to get installation token: {str(e)}")
            return False, f"Failed to get installation token: {str(e)}"

    async def search_github_app_repos_for_picker(self, org_name: str, query: str = ""):
        """Search GitHub App repositories for picker UI"""
        try:
            logger.info(f"Starting search for org: {org_name}, query: {query}")

            # Reuse your existing working logic from github_app_api_call
            success, repos_data = await self.github_app_api_call(org_name, operation="list_repos")

            logger.info(f"github_app_api_call returned: success={success}")
            if not success:
                logger.error(f"API call failed: {repos_data}")
                return False, repos_data

            logger.info(f"Found {len(repos_data)} repos")

            # Filter and format the results
            filtered_repos = []
            for repo in repos_data:
                if not query or query.lower() in repo['name'].lower():
                    filtered_repos.append({
                        'repo_name': f"{org_name}~{repo['name']}",  # Your naming convention
                        'repo_url': f"https://github.com/{repo['full_name']}.git",
                        'name': repo['name'],
                        'full_name': repo['full_name'],
                        'description': repo.get('description', ''),
                        'private': repo['private'],
                        'text': f"{repo['name']} - {repo.get('description', 'No description')}"  # For select2
                    })

            logger.info(f"Returning {len(filtered_repos)} filtered repos")
            return True, filtered_repos

        except Exception as e:
            logger.error(f"Failed to search GitHub App repos for picker: {str(e)}")
            return False, f"Failed to search repositories: {str(e)}"

    async def get_org_name_from_installation(self, installation_id: int) -> Tuple[bool, str]:
        """
        Resolve the owner login (username or org) for a GitHub App installation.
        Works with both new and old PyGithub; falls back to REST if needed.
        """
        try:
            # --- 1) Load app config exactly like the rest of your code does ---
            config = await self.db_manager.find_document('org_settings', {'setting_type': 'github_app'})
            if not config:
                return False, "GitHub App not configured"

            app_id = config.get("app_id")
            encrypted_key = config.get("private_key")
            if not app_id or not encrypted_key:
                return False, "App ID or private key missing"

            private_key = self.decrypt_data(encrypted_key)
            if not private_key or private_key == "DECRYPTION_FAILED":
                return False, "Failed to decrypt private key"

            try:
                app_id = int(app_id)
            except Exception:
                return False, "Stored GitHub App ID is not an integer"

            if isinstance(private_key, (bytes, bytearray)):
                private_key = private_key.decode("utf-8", errors="ignore")

            # --- 2) Try PyGithub modern path first ---
            try:
                from github import GithubIntegration  # already in your deps
                integration = GithubIntegration(app_id, private_key)
                installation = integration.get_installation(installation_id)  # new API (by id)
                owner_login = installation.account.login
                return True, owner_login
            except TypeError as te:
                # Older PyGithub path detected: expects (owner, repo)
                if "positional argument: 'repo'" not in str(te):
                    raise  # some other TypeError; bubble up

            # --- 3) Fallback: direct REST call with JWT (version-proof) ---
            now = int(time.time())
            payload = {
                "iat": now - 60,          # allow clock skew
                "exp": now + 9 * 60,      # < 10 minutes
                "iss": app_id
            }
            app_jwt = jwt.encode(payload, private_key, algorithm="RS256")

            url = f"https://api.github.com/app/installations/{installation_id}"
            headers = {
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "qubiva-app"
            }
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return False, f"GitHub API error ({resp.status_code}): {resp.text}"

            data = resp.json()
            account = data.get("account") or {}
            owner_login = account.get("login")
            if not owner_login:
                return False, "Installation account.login not found"

            return True, owner_login

        except Exception as e:
            return False, f"Failed to get organization name: {str(e)}"

    async def delete_github_app_configuration(self):
        """Delete GitHub App configuration and all installation mappings"""
        try:
            # Delete the GitHub App configuration from org_settings
            await self.db_manager.delete_document(
                'org_settings',
                {'setting_type': 'github_app'}
            )

            # Delete all installation mappings
            installations_result = await self.db_manager.delete_documents(
                'github_installations',
                {}  # Delete all installation mappings
            )

            logger.info(f"Deleted GitHub App config. Removed {installations_result} installation mappings.")
            return True, f"GitHub App configuration deleted successfully. Removed {installations_result} installation mappings."

        except Exception as e:
            logger.error(f"Failed to delete GitHub App configuration: {str(e)}")
            return False, f"Failed to delete GitHub App configuration: {str(e)}"

    async def validate_installation_belongs_to_app(self, installation_id: int):
        """
        Ensure the given installation_id belongs to the configured GitHub App.
        Returns (True, None) if valid, (False, "error message") if not.
        """
        try:
            config = await self.db_manager.find_document('org_settings', {'setting_type': 'github_app'})
            if not config:
                return False, "GitHub App not configured"

            app_id = int(config.get("app_id"))
            encrypted_key = config.get("private_key")
            private_key = self.decrypt_data(encrypted_key)
            if private_key == "DECRYPTION_FAILED":
                return False, "Failed to decrypt private key"
            if isinstance(private_key, (bytes, bytearray)):
                private_key = private_key.decode("utf-8", errors="ignore")

            # --- Try PyGithub first ---
            try:
                from github import GithubIntegration
                integration = GithubIntegration(app_id, private_key)
                installation = integration.get_installation(installation_id)  # may fail on older PyGithub
                if getattr(installation, "app_id", None) and int(installation.app_id) != app_id:
                    return False, f"Installation {installation_id} does not belong to App {app_id}"
                return True, None
            except TypeError as te:
                if "positional argument: 'repo'" not in str(te):
                    raise  # some other error -> bubble up

            # --- Fallback: REST API with JWT ---
            now = int(time.time())
            payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": app_id}
            app_jwt = jwt.encode(payload, private_key, algorithm="RS256")

            url = f"https://api.github.com/app/installations/{installation_id}"
            headers = {
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "qubiva-app"
            }
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return False, f"GitHub API error ({resp.status_code}): {resp.text}"

            data = resp.json()
            if int(data.get("app_id")) != app_id:
                return False, f"Installation {installation_id} does not belong to App {app_id}"

            return True, None

        except Exception as e:
            return False, f"Validation failed: {str(e)}"
