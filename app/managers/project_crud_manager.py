import logging
from app.managers.base import ManagerBase

logger = logging.getLogger('uvicorn.error')


class ProjectCrudManager(ManagerBase):
    def __init__(self, db_manager, kms_manager, rbac, scheduler, user_manager):
        super().__init__(db_manager, kms_manager)
        self.rbac = rbac
        self.scheduler = scheduler
        self.user_manager = user_manager

    async def get_project_details(self, project_name):
        try:
            # Fetch project details from the 'projects' collection
            project = await self.db_manager.find_document('projects', {'project_name': project_name})
            if not project:
                return False, "Project not found"

            project.pop('_id', None)  # Remove the MongoDB document ID from the results

            # Decrypt secrets
            if 'secrets' in project:
                decrypted_secrets = {}
                for key, encrypted_value in project['secrets'].items():
                    decrypted_secrets[key] = self.decrypt_data(encrypted_value)
                project['secrets'] = decrypted_secrets

            return True, project
        except Exception as e:
            logger.error(f"Failed to get project details for '{project_name}': {str(e)}")
            return False, f"Failed to get project details: {str(e)}"

    async def get_project(self, project_name: str):
        """
        Backward-compatible project fetch used by older API handlers.

        Historically some handlers expected a project payload containing an
        embedded `cloud_accounts` list. After normalization, cloud accounts are
        stored in a separate collection. This helper restores the expected shape
        without changing callers.
        """
        try:
            success, project = await self.get_project_details(project_name)
            if not success:
                return False, project

            cloud_accounts = await self.db_manager.find_documents(
                'cloud_accounts',
                {'project_name': project_name}
            )

            project['cloud_accounts'] = [
                {
                    'account_id': account.get('account_id'),
                    'cloud_platform': account.get('cloud_platform')
                }
                for account in cloud_accounts
            ]

            return True, project
        except Exception as e:
            logger.error(f"Failed to get project '{project_name}': {str(e)}")
            return False, f"Failed to get project: {str(e)}"

    async def create_project(self, project_name: str, description: str, members: list[dict[str, any]] = None, variables: dict = None, secrets: dict = None, acting_user: str = None):
        try:
            logger.debug("Attempting to create a new project: %s", project_name)
            if await self.db_manager.find_document('projects', {'project_name': project_name}):
                return False, "Project creation failed: Project name already exists"

            project_data = {
                'project_name': project_name,
                'description': description,
                'members': [],
                'variables': variables or {},
                'secrets': {},
                **self._audit_create(acting_user),
            }

            # Encrypt secrets
            if secrets:
                for key, value in secrets.items():
                    project_data['secrets'][key] = self.encrypt_data(value)

            await self.db_manager.insert_document('projects', project_data)
            logger.info("Project created successfully: %s", project_name)

            # If members are provided, add them to the project
            if members:
                success, message = await self.add_members_to_project(project_name, members)
                if not success:
                    logger.warning(f"Project created, but failed to add one or more members: {message}")
                    return False, "Project created, but failed to add one or more members"

            return True, "Project created successfully with variables and secrets"
        except Exception as e:
            logger.error(f"Failed to create project '{project_name}': {str(e)}")
            return False, f"Failed to create project: {str(e)}"

    async def delete_project(self, project_name: str, acting_user: str = None):
        # step 0: Delete all schedules
        try:
            schedule_result = await self.scheduler.delete_project_schedules(project_name)
            if schedule_result["status"] == "error":
                logger.error(f"Failed to clean up all schedules for project '{project_name}': {schedule_result}")
            elif schedule_result["status"] == "partial_success":
                logger.warning(f"Some schedules couldn't be cleaned up for project '{project_name}': {schedule_result}")
            else:
                logger.info(f"Successfully cleaned up all schedules for project '{project_name}'")
        except Exception as e:
            logger.error(f"Error during schedule cleanup for project '{project_name}': {str(e)}")

        try:
            # Step 1: Get the list of all collections in the database
            collections = await self.db_manager.get_collection_names()

            if not collections:
                logger.warning(f"No collections found in the database to delete project '{project_name}'")
                return False, "No collections found in the database"

            # Step 2: Iterate over each collection except 'projects'
            for collection in collections:
                if collection == "projects":
                    continue  # Skip 'projects' collection for now

                try:
                    logger.debug(f"Checking collection '{collection}' for project deletion")

                    # Check if the collection contains documents with a 'project_name' field
                    sample_doc = await self.db_manager.find_document(collection, {})

                    if not sample_doc:
                        logger.debug(f"Collection '{collection}' is empty, skipping.")
                        continue

                    if 'project_name' not in sample_doc:
                        logger.debug(f"Collection '{collection}' does not contain 'project_name' field, skipping.")
                        continue

                    # Delete documents where 'project_name' matches the provided project name
                    delete_result = await self.db_manager.delete_documents(collection, {'project_name': project_name})

                    if delete_result > 0:
                        logger.info(f"Deleted {delete_result} documents from '{collection}' for project '{project_name}'")
                    else:
                        logger.info(f"No documents to delete in '{collection}' for project '{project_name}'")

                except Exception as e:
                    logger.error(f"Failed to delete documents from '{collection}' for project '{project_name}': {str(e)}")
                    return False, f"Failed to delete documents from '{collection}': {str(e)}"

            # Step 3: Before deleting the 'projects' collection, get the project details
            project_document = await self.db_manager.find_document('projects', {'project_name': project_name})
            if not project_document:
                logger.warning(f"Project '{project_name}' not found in 'projects' collection.")
                return False, f"Project '{project_name}' not found"

            # Step 4: Extract member usernames from the project document
            member_usernames = [member['username'] for member in project_document.get('members', [])]

            # Step 5: Update each user document by removing the project from their projects list
            for username in member_usernames:
                try:
                    # Remove the project from the user's 'projects' array
                    update_result = await self.db_manager.update_one_document(
                        'users',
                        {'username': username},
                        {'$pull': {'projects': project_name}}
                    )
                    if update_result['matched_count'] == 0:
                        logger.warning(f"User '{username}' not found when removing project '{project_name}'")
                    elif update_result['modified_count'] == 0:
                        logger.info(f"Project '{project_name}' was not in user '{username}' projects. No action needed.")
                    else:
                        logger.info(f"Removed project '{project_name}' from user '{username}' successfully.")
                except Exception as e:
                    logger.error(f"Failed to update user '{username}' for project '{project_name}': {str(e)}")
                    return False, f"Failed to update user '{username}': {str(e)}"

            # Step 6: Now, delete the project document from the 'projects' collection
            try:
                delete_project_result = await self.db_manager.delete_document('projects', {'project_name': project_name})
                if delete_project_result > 0:
                    logger.info(f"Deleted project '{project_name}' successfully from 'projects' collection")
                else:
                    logger.warning(f"Project '{project_name}' not found in 'projects' collection for deletion")
                    return False, "Project not found for deletion"
            except Exception as e:
                logger.error(f"Failed to delete project '{project_name}' from 'projects' collection: {str(e)}")
                return False, f"Failed to delete project from 'projects' collection: {str(e)}"

            logger.info(f"Successfully deleted project '{project_name}' from all relevant collections")
            return True, f"Project '{project_name}' deleted successfully"

        except Exception as e:
            logger.error(f"Failed to delete project '{project_name}': {str(e)}")
            return False, f"Failed to delete project: {str(e)}"

    async def update_project(self, project_name: str, new_description: str = None, new_members: list = None, new_variables: dict = None, new_secrets: dict = None, acting_user: str = None):
        try:
            # Fetch the current project details
            project = await self.db_manager.find_document('projects', {'project_name': project_name})
            if not project:
                return False, f"Project '{project_name}' not found"

            # Update the project description if provided
            if new_description is not None:
                project['description'] = new_description

            if new_members is not None:
                current_members = {member['username']: member for member in project.get('members', [])}
                new_member_usernames = {member['username'] for member in new_members}

                # Handle removed members
                for username in current_members.keys() - new_member_usernames:
                    await self.remove_project_from_user(username, project_name)

                # Update or add new members
                for new_member in new_members:
                    username = new_member['username']
                    new_member['roles']

                    if username not in current_members:
                        # Add new member to project
                        await self.add_project_to_user(username, project_name)

                # Update the project's member list
                project['members'] = new_members

            # Update variables if provided
            if new_variables is not None:
                project['variables'] = new_variables

            # Update secrets if provided
            if new_secrets is not None:
                project['secrets'] = {}
                for key, value in new_secrets.items():
                    project['secrets'][key] = self.encrypt_data(value)

            # Perform the update in the database
            update_result = await self.db_manager.update_one_document(
                'projects',
                {'project_name': project_name},
                {'$set': {
                    'description': project['description'],
                    'members': project.get('members', []),
                    'variables': project.get('variables', {}),
                    'secrets': project.get('secrets', {}),
                    **self._audit_update(acting_user),
                }}
            )

            if update_result['matched_count'] > 0:
                return True, "Project updated successfully"
            else:
                return False, f"Project '{project_name}' not found"

        except Exception as e:
            logger.error(f"Failed to update project '{project_name}': {str(e)}")
            return False, f"Failed to update project: {str(e)}"

    async def remove_project_from_user(self, username: str, project_name: str):
        try:
            update_result = await self.db_manager.update_one_document(
                'users',
                {'username': username},
                {'$pull': {'projects': project_name}}
            )
            if update_result['matched_count'] == 0:
                logger.warning(f"User '{username}' not found when removing project '{project_name}'")
            elif update_result['modified_count'] == 0:
                logger.info(f"Project '{project_name}' was not in user '{username}' projects. No action needed.")
        except Exception as e:
            logger.error(f"Failed to remove project '{project_name}' from user '{username}': {str(e)}")

    async def add_project_to_user(self, username: str, project_name: str):
        try:
            update_result = await self.db_manager.update_one_document(
                'users',
                {'username': username},
                {'$addToSet': {'projects': project_name}}
            )
            logger.debug(update_result)
            if update_result['matched_count'] == 0:
                logger.warning(f"User '{username}' not found when adding project '{project_name}'")
            elif update_result['modified_count'] == 0:
                logger.info(f"Project '{project_name}' was already in user '{username}' projects. No action needed.")
        except Exception as e:
            logger.error(f"Failed to add project '{project_name}' to user '{username}': {str(e)}")
        return update_result

    # Member Management Methods
    async def add_member_to_project(self, project_name, username, roles, acting_user: str = None):
        logger.debug(f"Roles: {roles}")
        try:
            # Ensure roles can be empty but must be a list
            if roles is None:
                roles = []

            # Check if the user exists
            user_exists, msg = await self.user_manager.user_exists(username)
            if not user_exists:
                return False, f"User does not exist: {msg}"

            logger.debug(f"Adding user '{username}' to project '{project_name}' with roles {roles}")

            # Add the member to the project
            project_update_result = await self.db_manager.update_one_document(
                'projects',
                {'project_name': project_name},
                {'$addToSet': {'members': {'username': username, 'roles': roles}}}
            )
            logger.debug(f"Project update result: {project_update_result}")
            if project_update_result['modified_count'] > 0:
                # Now, add the project to the user's list of projects
                try:
                    user_update_result = await self.add_project_to_user(username, project_name)
                    logger.debug(type(user_update_result))
                    logger.debug(f"Add project to user result: {user_update_result}")

                    if user_update_result['modified_count'] > 0 or user_update_result.get('upserted_id'):
                        logger.debug(f"User '{username}' added to project '{project_name}' successfully.")
                        return True, "Member added successfully"
                    else:
                        logger.warning(f"Member added to project '{project_name}', but failed to add project to user '{username}'")
                        return False, "Member added to project, but failed to add project to user"
                except Exception as inner_e:
                    logger.error(f"Exception occurred while adding project '{project_name}' to user '{username}': {str(inner_e)}")
                    return False, f"Member added to project, but failed to add project to user due to an error: {str(inner_e)}"
            else:
                logger.warning(f"Failed to add member '{username}' to project '{project_name}'. No changes made.")
                return False, "Failed to add member to project"
        except Exception as e:
            logger.error(f"Exception occurred while adding member '{username}' to project '{project_name}': {str(e)}")
            return False, f"Failed to add member to project: {str(e)}"

    async def add_members_to_project(self, project_name: str, members: list[dict]):
        try:
            if not all(isinstance(member.get('roles', []), list) for member in members):
                return False, "Member roles must be provided as lists"
            results = []
            for member in members:
                success, message = await self.add_member_to_project(project_name, member['username'], member['roles'])
                results.append(success)
                if not success:
                    logger.error(f"Failed to add member '{member['username']}' to project '{project_name}': {message}")
            if all(results):
                return True, "All members added successfully"
            return False, "One or more members could not be added successfully"
        except Exception as e:
            logger.error(f"Failed to add members to project '{project_name}': {str(e)}")
            return False, f"Failed to add members to project: {str(e)}"

    async def remove_member_from_project(self, project_name: str, username: str, acting_user: str = None):
        try:
            # Check if the user exists
            user_exists, msg = await self.user_manager.user_exists(username)
            if not user_exists:
                return False, f"User does not exist: {msg}"

            # Remove the member from the project
            project_update_result = await self.db_manager.update_one_document(
                'projects',
                {'project_name': project_name},
                {'$pull': {'members': {'username': username}}}
            )
            if project_update_result['modified_count'] > 0:
                # Now, remove the project from the user's list of projects
                user_update_result = await self.db_manager.update_one_document(
                    'users',
                    {'username': username, 'projects': project_name},
                    {'$pull': {'projects': project_name}}
                )

                if user_update_result['matched_count'] == 0:
                    logger.warning(f"User '{username}' does not have project '{project_name}' listed. Nothing to remove.")
                    return True, "Member removed from project, but project was not listed in user's projects"

                if user_update_result['modified_count'] > 0:
                    return True, "Member removed successfully"
                else:
                    logger.warning(f"Project '{project_name}' was not removed from user '{username}' projects. It might not have been listed.")
                    return True, "Member removed from project, but project was not listed in user's projects"

            return False, "Failed to remove member from project"
        except Exception as e:
            logger.error(f"Failed to remove member '{username}' from project '{project_name}': {str(e)}")
            return False, f"Failed to remove member from project: {str(e)}"

    async def remove_members_from_project(self, project_name: str, usernames: list[str]):
        try:
            results = []
            for username in usernames:
                success, message = await self.remove_member_from_project(project_name, username)
                results.append(success)
                if not success:
                    logger.error(f"Failed to remove member '{username}' from project '{project_name}': {message}")
            if all(results):
                return True, "All members removed successfully"
            return False, "One or more members could not be removed successfully"
        except Exception as e:
            logger.error(f"Failed to remove members from project '{project_name}': {str(e)}")
            return False, f"Failed to remove members from project: {str(e)}"

    async def get_project_details_for_projects(self, username, project_names=None, is_org_user=False):
        try:
            project_details = {}

            # If project_names is not provided, fetch all projects
            if project_names is None:
                all_projects = await self.db_manager.find_documents('projects', {})
                project_names = [project['project_name'] for project in all_projects]

            for project_name in project_names:
                project = await self.db_manager.find_document('projects', {'project_name': project_name})
                if project:
                    project_info = {
                        'description': project.get('description', 'No description available'),
                        'created_at': project.get('created_at', 'N/A'),
                        'updated_at': project.get('updated_at', 'N/A')
                    }

                    if is_org_user:
                        # For org users, include all projects
                        project_details[project_name] = project_info
                    else:
                        # For regular users, only include if they are a member
                        for member in project.get('members', []):
                            if member['username'] == username:
                                project_details[project_name] = project_info
                                break

            return True, project_details
        except Exception as e:
            logger.error(f"Failed to get project details: {str(e)}")
            return False, f"Failed to get project details: {str(e)}"

    async def get_all_projects(self):
        try:
            all_projects = await self.db_manager.find_documents('projects', {})

            roles_by_project = {}
            for project in all_projects:
                project_name = project['project_name']
                project_info = {
                    'roles': ['*'],  # Wildcard role
                    'description': project.get('description', 'No description available')
                }
                roles_by_project[project_name] = project_info

            return True, roles_by_project
        except Exception as e:
            logger.error(f"Failed to get all projects with wildcard roles: {str(e)}")
            return False, f"Failed to get all projects with wildcard roles: {str(e)}"

    async def get_user_roles_by_project(self, username, project_name, is_org_user=False):
        try:
            project = await self.db_manager.find_document('projects', {'project_name': project_name})
            if not project:
                return False, "Project not found"

            # Check if the user is a direct member of the project
            for member in project.get('members', []):
                if member['username'] == username:
                    return True, member.get('roles', [])

            # If the user is not a direct member but is an org user, return wildcard role
            if is_org_user:
                return True, ['*']

            # If the user is neither a project member nor an org user
            return False, "User is not a member of the project"
        except Exception as e:
            logger.error(f"Failed to get user roles for project '{project_name}': {str(e)}")
            return False, f"Failed to get user roles by project: {str(e)}"

    async def get_project_members(self, project_name: str, search_query: str = ""):
        try:
            # Fetch the project document by project name
            project = await self.db_manager.find_document('projects', {'project_name': project_name})
            if not project:
                return False, "Project not found"

            # Extract members from the project document
            members = project.get('members', [])
            if not members:
                return False, "No members found in the project"

            # Collect email addresses from the members, filtering based on the search query
            email_addresses = [
                member['username'] for member in members
                if search_query.lower() in member['username'].lower()
            ]

            if not email_addresses:
                return False, "No members matched the search query"

            return True, email_addresses
        except Exception as e:
            logger.error(f"Failed to get project members for '{project_name}': {str(e)}")
            return False, f"Failed to get project members: {str(e)}"

    async def search_projects(self, query: str):
        try:
            regex_query = {'$regex': query, '$options': 'i'}
            projects = await self.db_manager.find_documents('projects', {
                '$or': [
                    {'project_name': regex_query},
                    {'description': regex_query}
                ]
            })

            search_results = [
                {
                    "project_name": project.get("project_name"),
                    "description": project.get("description"),
                }
                for project in projects
            ]

            return True, search_results
        except Exception as e:
            logger.error(f"Failed to search projects: {str(e)}")
            return False, []
