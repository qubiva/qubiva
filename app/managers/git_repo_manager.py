import logging
from app.managers.base import ManagerBase

logger = logging.getLogger('uvicorn.error')


class GitRepoManager(ManagerBase):
    def __init__(self, db_manager, kms_manager):
        super().__init__(db_manager, kms_manager)

    async def add_github_repo_to_project(self, project_name, repo_details, acting_user: str = None):
        try:
            # Ensure required fields are provided
            if 'repo_name' not in repo_details or 'repo_url' not in repo_details:
                return False, "Repository name and URL must be provided"

            # Check if the repository URL already exists in the database for this project
            existing_repo = await self.db_manager.find_document(
                'github_repos',
                {
                    'project_name': project_name,
                    'repo_url': repo_details['repo_url']
                }
            )
            if existing_repo:
                return False, f"GitHub repository with URL '{repo_details['repo_url']}' already exists in project '{project_name}'"

            # Add the project name to the repo details
            repo_details['project_name'] = project_name

            # Encrypt the token if it is provided
            if 'token' in repo_details and repo_details['token']:
                repo_details['token'] = self.encrypt_data(repo_details['token'])

            # Insert the document into the database
            repo_details.update(self._audit_create(acting_user))
            await self.db_manager.insert_document('github_repos', repo_details)
            return True, "GitHub repository added successfully"
        except Exception as e:
            logger.error(f"Failed to add GitHub repository to project '{project_name}': {str(e)}")
            return False, f"Failed to add GitHub repository: {str(e)}"

    async def get_github_repos_by_project(self, project_name):
        try:
            repos = await self.db_manager.find_documents('github_repos', {'project_name': project_name})
            if repos:
                for repo in repos:
                    if 'token' in repo and repo['token']:
                        repo['token'] = self.decrypt_data(repo['token'])
                return True, repos
            return False, "No GitHub repositories found for this project"
        except Exception as e:
            logger.error(f"Failed to get GitHub repositories for project '{project_name}': {str(e)}")
            return False, f"Failed to get GitHub repositories: {str(e)}"

    async def update_github_repo(self, project_name, repo_name, updated_repo_details, acting_user: str = None):
        try:
            # Only allow updating specific fields
            allowed_fields = {
                'branch',
                'terraform_config_path',
                'discovery_queries_path',
                'custom_benchmark_path',
                'policy_governance_path',
                'token'
            }
            update_data = {k: v for k, v in updated_repo_details.items() if k in allowed_fields}

            # Encrypt the token if it is present and not None
            if 'token' in update_data and update_data['token']:  # Check if token exists and is not empty
                try:
                    update_data['token'] = self.encrypt_data(update_data['token'])
                except Exception as E:
                    logger.error(f"Error encrypting token: {str(E)}")
                    raise E

            # Update the document in the database
            update_data.update(self._audit_update(acting_user))
            result = await self.db_manager.update_one_document(
                'github_repos',
                {'project_name': project_name, 'repo_name': repo_name},
                {'$set': update_data}
            )

            if result['modified_count'] > 0:
                return True, "GitHub repository updated successfully"
            return False, "GitHub repository update failed"
        except Exception as e:
            logger.error(f"Failed to update GitHub repository for project '{project_name}': {str(e)}")
            return False, f"Failed to update GitHub repository: {str(e)}"

    async def delete_github_repo(self, project_name, repo_name, acting_user: str = None):
        try:
            # STEP 1: Find all workspaces that reference this GitHub repo
            referenced_workspaces = await self.db_manager.find_documents(
                'workspaces',
                {'project_name': project_name, 'github_repo_name': repo_name}
            )

            # STEP 2: Update all referencing workspaces to remove the GitHub repo reference
            if referenced_workspaces:
                for workspace in referenced_workspaces:
                    try:
                        update_result = await self.db_manager.update_one_document(
                            'workspaces',
                            {
                                'project_name': project_name,
                                'name': workspace['name']
                            },
                            {
                                '$unset': {'github_repo_name': ''}
                            }
                        )
                        if update_result['modified_count'] > 0:
                            logger.info(f"Updated workspace {workspace['name']} to remove GitHub repo reference")
                    except Exception as e:
                        logger.error(f"Failed to update workspace {workspace['name']}: {str(e)}")

            # STEP 3: Delete the GitHub repo (original logic)
            result = await self.db_manager.delete_document(
                'github_repos',
                {'project_name': project_name, 'repo_name': repo_name}
            )

            if result > 0:
                affected_workspaces = len(referenced_workspaces) if referenced_workspaces else 0
                if affected_workspaces > 0:
                    return True, f"GitHub repository deleted successfully. {affected_workspaces} workspace(s) updated to remove repository reference."
                else:
                    return True, "GitHub repository deleted successfully"
            return False, "GitHub repository deletion failed: Repository not found"
        except Exception as e:
            logger.error(f"Failed to delete GitHub repository from project '{project_name}': {str(e)}")
            return False, f"Failed to delete GitHub repository: {str(e)}"

    async def get_github_repo_details(self, project_name, repo_name):
        logger.debug(f"looking for {repo_name}")
        try:
            repo = await self.db_manager.find_document(
                'github_repos',
                {'project_name': project_name, 'repo_name': repo_name}
            )
            if repo:
                if 'token' in repo and repo['token']:
                    repo['token'] = self.decrypt_data(repo['token'])
                return True, repo
            return False, "GitHub repository not found"
        except Exception as e:
            logger.error(f"Failed to get GitHub repository details for project '{project_name}': {str(e)}")
            return False, f"Failed to get GitHub repository details: {str(e)}"

    async def search_github_repos(self, project_name: str, query: str):
        try:
            regex_query = {'$regex': query, '$options': 'i'}
            github_repos = await self.db_manager.find_documents('github_repos', {
                'project_name': project_name,
                '$or': [
                    {'repo_name': regex_query},
                    {'repo_url': regex_query}
                ]
            })

            search_results = [
                {
                    "id": str(repo.get("_id")),
                    "repo_name": repo.get("repo_name"),
                    "repo_url": repo.get("repo_url"),
                    "text": f"{repo.get('repo_name')} - {repo.get('repo_url')}"
                }
                for repo in github_repos
            ]

            return True, search_results
        except Exception as e:
            logger.error(f"Failed to search GitHub repos for project '{project_name}': {str(e)}")
            return False, []
