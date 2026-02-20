import logging
import traceback
from typing import Dict
from app.managers.base import ManagerBase

logger = logging.getLogger('uvicorn.error')


class CloudAccountManager(ManagerBase):
    def __init__(self, db_manager, kms_manager, credential_manager):
        super().__init__(db_manager, kms_manager)
        self.credential_manager = credential_manager

    async def add_cloud_account_to_project(self, project_name, cloud_account, acting_user: str = None):
        try:
            if 'cloud_platform' not in cloud_account or 'account_id' not in cloud_account:
                return False, "Cloud platform and account ID must be provided"

            # Validate that either auth_secrets or credential_reference is provided, but not both
            has_auth_secrets = 'auth_secrets' in cloud_account and cloud_account['auth_secrets']
            has_credential_ref = 'credential_reference' in cloud_account and cloud_account['credential_reference']

            if not has_auth_secrets and not has_credential_ref:
                return False, "Either 'auth_secrets' or 'credential_reference' must be provided"

            if has_auth_secrets and has_credential_ref:
                return False, "Cannot specify both 'auth_secrets' and 'credential_reference'"

            if has_auth_secrets:
                cloud_account.pop('credential_reference', None)  # Remove if somehow present

            if has_credential_ref:
                cloud_account.pop('auth_secrets', None)  # Remove if somehow present

            # If credential_reference is used, validate it exists
            if has_credential_ref:
                credential_exists = await self.db_manager.find_document(
                    'credentials',
                    {'project_name': project_name, 'credential_name': cloud_account['credential_reference']}
                )
                if not credential_exists:
                    return False, f"Credential '{cloud_account['credential_reference']}' not found"

            existing_account = await self.db_manager.find_document(
                'cloud_accounts',
                {
                    'project_name': project_name,
                    'cloud_platform': cloud_account['cloud_platform'],
                    'account_id': cloud_account['account_id']
                }
            )

            if existing_account:
                return False, f"Cloud account with account_id '{cloud_account['account_id']}' and platform '{cloud_account['cloud_platform']}' already exists in project '{project_name}'"

            cloud_account['project_name'] = project_name

            # Only encrypt auth_secrets if it's provided (not credential_reference)
            if has_auth_secrets and isinstance(cloud_account['auth_secrets'], dict):
                auth_type = cloud_account['auth_secrets'].get('type')

                if auth_type == 'external_certificate_authority':
                    # AWS External CA - encrypt certificate and key
                    for key in ['certificate', 'key']:
                        if key in cloud_account['auth_secrets']:
                            cloud_account['auth_secrets'][key] = self.encrypt_data(cloud_account['auth_secrets'][key])
                            logger.info(f"Encrypted {key} for account {cloud_account['account_id']}")

                elif auth_type == 'key_pair':
                    # AWS Key Pair - encrypt access key ID and secret
                    for key in ['access_key_id', 'secret_access_key']:
                        if key in cloud_account['auth_secrets']:
                            cloud_account['auth_secrets'][key] = self.encrypt_data(cloud_account['auth_secrets'][key])
                            logger.info(f"Encrypted {key} for account {cloud_account['account_id']}")

                elif auth_type == 'azure_service_principal':
                    # Azure Service Principal - encrypt client secret only
                    if 'azure_client_secret' in cloud_account['auth_secrets']:
                        cloud_account['auth_secrets']['azure_client_secret'] = self.encrypt_data(cloud_account['auth_secrets']['azure_client_secret'])
                        logger.info(f"Encrypted azure_client_secret for account {cloud_account['account_id']}")

                elif auth_type == 'gcp_service_account':
                    # GCP Service Account - encrypt the entire credentials JSON
                    if 'google_application_credentials' in cloud_account['auth_secrets']:
                        cloud_account['auth_secrets']['google_application_credentials'] = self.encrypt_data(cloud_account['auth_secrets']['google_application_credentials'])
                        logger.info(f"Encrypted google_application_credentials for account {cloud_account['account_id']}")

            # Encrypting variables marked as secrets
            if 'secrets' in cloud_account and isinstance(cloud_account['secrets'], dict):
                for key, value in cloud_account['secrets'].items():
                    cloud_account['secrets'][key] = self.encrypt_data(value)
                    logger.info(f"Encrypted secret {key} for account {cloud_account['account_id']}")

            cloud_account.update(self._audit_create(acting_user))
            await self.db_manager.insert_document('cloud_accounts', cloud_account)
            logger.info(f"Cloud account {cloud_account['account_id']} added successfully to project {project_name}")
            return True, "Cloud account added successfully"
        except Exception as e:
            logger.error(f"Failed to add cloud account to project '{project_name}': {str(e)}")
            return False, f"Failed to add cloud account to project: {str(e)}"

    async def get_cloud_accounts_by_project_name(self, project_name):
        try:
            cloud_accounts = await self.db_manager.find_documents('cloud_accounts', {'project_name': project_name})
            logger.info(f"Found {len(cloud_accounts)} cloud accounts for project {project_name}")

            if cloud_accounts:
                for account in cloud_accounts:
                    logger.debug(f"Processing account: {account['account_id']}")

                    # NEW: Handle credential reference resolution
                    if 'credential_reference' in account:
                        try:
                            resolved_auth_secrets = await self.credential_manager._resolve_credential_reference(
                                project_name,
                                account['credential_reference']
                            )
                            # Replace credential_reference with resolved auth_secrets
                            account['auth_secrets'] = resolved_auth_secrets
                            account.pop('credential_reference', None)
                        except Exception as e:
                            logger.error(f"Failed to resolve credential reference for account {account['account_id']}: {str(e)}")
                            account['auth_secrets'] = {'error': f'Failed to resolve credential: {str(e)}'}

                    # Continue with existing decryption logic for embedded auth_secrets
                    if 'auth_secrets' in account and isinstance(account['auth_secrets'], dict):
                        if account['auth_secrets'].get('type') == 'external_certificate_authority':
                            for key in ['certificate', 'key']:
                                if key in account['auth_secrets']:
                                    try:
                                        decrypted_value = self.decrypt_data(account['auth_secrets'][key])
                                        account['auth_secrets'][key] = decrypted_value
                                        logger.info(f"Successfully decrypted {key} for account {account['account_id']}")
                                    except Exception as e:
                                        logger.error(f"Failed to decrypt {key} for account {account['account_id']}: {str(e)}")
                                        account['auth_secrets'][key] = f"DECRYPTION_FAILED: {str(e)}"

                            # ARNs are not encrypted, so we just log their presence
                            for arn_key in ['profile_arn', 'role_arn', 'trust_anchor_arn']:
                                if arn_key in account['auth_secrets']:
                                    logger.info(f"Retrieved {arn_key} for account {account['account_id']}")

                    # Decrypting variables marked as secrets
                    if 'secrets' in account and isinstance(account['secrets'], dict):
                        for key, value in account['secrets'].items():
                            try:
                                account['secrets'][key] = self.decrypt_data(value)
                                logger.info(f"Successfully decrypted secret {key} for account {account['account_id']}")
                            except Exception as e:
                                logger.error(f"Failed to decrypt secret {key} for account {account['account_id']}: {str(e)}")
                                account['secrets'][key] = f"DECRYPTION_FAILED: {str(e)}"

                    # Variables are retrieved directly without decryption
                    if 'variables' in account:
                        logger.info(f"Account {account['account_id']} has {len(account['variables'])} variables (not decrypted)")

                return True, cloud_accounts
            return False, "No cloud accounts found for this project"
        except Exception as e:
            logger.error(f"Failed to get cloud accounts for project '{project_name}': {str(e)}")
            logger.error(traceback.format_exc())
            return False, f"Failed to get cloud accounts: {str(e)}"

    async def update_project_cloud_account(self, project_name: str, cloud_platform: str, account_id: str, updated_account: Dict, acting_user: str = None):
        try:
            # Fetch the existing account
            existing_account = await self.db_manager.find_document(
                'cloud_accounts',
                {'project_name': project_name, 'cloud_platform': cloud_platform, 'account_id': account_id}
            )

            if not existing_account:
                return False, "Cloud account not found"

            # IMPORTANT: Remove _id first, before any modifications
            existing_account.pop('_id', None)

            # Validate auth method (either auth_secrets or credential_reference, not both)
            has_auth_secrets = 'auth_secrets' in updated_account and updated_account['auth_secrets']
            has_credential_ref = 'credential_reference' in updated_account and updated_account['credential_reference']

            if not has_auth_secrets and not has_credential_ref:
                return False, "Either 'auth_secrets' or 'credential_reference' must be provided"

            if has_auth_secrets and has_credential_ref:
                return False, "Cannot specify both 'auth_secrets' and 'credential_reference'"

            # Prepare the update document
            unset_fields = {}

            # Clear the other auth method
            if has_auth_secrets:
                logger.debug("Updating with auth_secrets")
                existing_account.pop('credential_reference', None)
                unset_fields['credential_reference'] = ''

                # Update auth_secrets with proper encryption
                existing_account['auth_secrets'] = {}
                auth_type = updated_account['auth_secrets'].get('type')

                for key, value in updated_account['auth_secrets'].items():
                    if auth_type == 'external_certificate_authority' and key in ['certificate', 'key']:
                        existing_account['auth_secrets'][key] = self.encrypt_data(value)
                    elif auth_type == 'key_pair' and key in ['access_key_id', 'secret_access_key']:
                        existing_account['auth_secrets'][key] = self.encrypt_data(value)
                    elif auth_type == 'azure_service_principal' and key == 'azure_client_secret':
                        existing_account['auth_secrets'][key] = self.encrypt_data(value)
                    elif auth_type == 'gcp_service_account' and key == 'google_application_credentials':
                        existing_account['auth_secrets'][key] = self.encrypt_data(value)
                    else:
                        # For non-sensitive fields (ARNs, client_id, tenant_id, etc.)
                        existing_account['auth_secrets'][key] = value

            if has_credential_ref:
                logger.debug("Updating with credential_reference")
                # Validate credential exists
                credential_exists = await self.db_manager.find_document(
                    'credentials',
                    {'project_name': project_name, 'credential_name': updated_account['credential_reference']}
                )
                if not credential_exists:
                    return False, f"Credential '{updated_account['credential_reference']}' not found"

                existing_account.pop('auth_secrets', None)
                unset_fields['auth_secrets'] = ''
                existing_account['credential_reference'] = updated_account['credential_reference']

            # Overwrite variables
            if 'variables' in updated_account:
                existing_account['variables'] = updated_account['variables']

            # Overwrite and encrypt secrets
            if 'secrets' in updated_account:
                existing_account['secrets'] = {}
                for key, value in updated_account['secrets'].items():
                    existing_account['secrets'][key] = self.encrypt_data(value)

            # Build the update document
            existing_account.update(self._audit_update(acting_user))
            update_doc = {'$set': existing_account}
            if unset_fields:
                update_doc['$unset'] = unset_fields

            # Update the document in the database
            result = await self.db_manager.update_one_document(
                'cloud_accounts',
                {'project_name': project_name, 'cloud_platform': cloud_platform, 'account_id': account_id},
                update_doc
            )

            if result['modified_count'] > 0:
                return True, "Cloud account updated successfully"
            return False, "No changes were made to the cloud account"
        except Exception as e:
            logger.error(f"Failed to update cloud account for project '{project_name}': {str(e)}")
            return False, f"Failed to update cloud account: {str(e)}"

    async def delete_cloud_account_from_project(self, project_name, account_id, acting_user: str = None):
        try:
            # STEP 1: Find all workspaces that reference this cloud account
            referenced_workspaces = await self.db_manager.find_documents(
                'workspaces',
                {'project_name': project_name, 'cloud_account': account_id}
            )

            # STEP 2: Update all referencing workspaces to remove the cloud account reference
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
                                '$unset': {'cloud_account': '', 'cloud_platform': ''}
                            }
                        )
                        if update_result['modified_count'] > 0:
                            logger.info(f"Updated workspace {workspace['name']} to remove cloud account reference")
                    except Exception as e:
                        logger.error(f"Failed to update workspace {workspace['name']}: {str(e)}")

            # STEP 3: Delete the cloud account (original logic)
            result = await self.db_manager.delete_document(
                'cloud_accounts',
                {'project_name': project_name, 'account_id': account_id}
            )

            if result > 0:
                affected_workspaces = len(referenced_workspaces) if referenced_workspaces else 0
                if affected_workspaces > 0:
                    return True, f"Cloud account deleted successfully. {affected_workspaces} workspace(s) updated to remove cloud account reference."
                else:
                    return True, "Cloud account deleted successfully"
            return False, "Cloud account deletion failed: Account not found"
        except Exception as e:
            logger.error(f"Failed to delete cloud account from project '{project_name}': {str(e)}")
            return False, f"Failed to delete cloud account: {str(e)}"

    async def get_cloud_account_details(self, project_name, cloud_platform, account_id):
        try:
            cloud_account = await self.db_manager.find_document(
                'cloud_accounts',
                {'project_name': project_name, 'cloud_platform': cloud_platform, 'account_id': account_id}
            )
            if not cloud_account:
                return False, "Cloud account not found"

            # Handle credential reference resolution
            credential_was_resolved = False
            original_credential_reference = None  # NEW: Store original reference

            if 'credential_reference' in cloud_account:
                original_credential_reference = cloud_account['credential_reference']  # NEW: Save it
                try:
                    resolved_auth_secrets = await self.credential_manager._resolve_credential_reference(
                        project_name,
                        cloud_account['credential_reference']
                    )
                    cloud_account['auth_secrets'] = resolved_auth_secrets
                    cloud_account.pop('credential_reference', None)
                    credential_was_resolved = True
                except Exception as e:
                    logger.error(f"Failed to resolve credential reference for account {account_id}: {str(e)}")
                    return False, f"Failed to resolve credential reference: {str(e)}"

            # NEW: If we resolved a credential reference, add UI-friendly info
            if credential_was_resolved and original_credential_reference:
                cloud_account['credential_reference'] = original_credential_reference
                cloud_account['credential_type'] = cloud_account['auth_secrets'].get('type')
                cloud_account['credential_reference_details'] = {
                    'credential_name': original_credential_reference,
                    'credential_type': cloud_account['auth_secrets'].get('type')
                }

            # Only decrypt inline auth_secrets if we didn't resolve from credential reference
            if 'auth_secrets' in cloud_account and not credential_was_resolved:
                auth_type = cloud_account['auth_secrets'].get('type')

                if auth_type == 'external_certificate_authority':
                    for key in ['certificate', 'key']:
                        if key in cloud_account['auth_secrets']:
                            decrypted_value = self.decrypt_data(cloud_account['auth_secrets'][key])
                            cloud_account['auth_secrets'][key] = decrypted_value
                            logger.info(f"Successfully decrypted {key} for account {account_id}")

                    # ARNs are not encrypted, so we just ensure they're present
                    for arn_key in ['profile_arn', 'role_arn', 'trust_anchor_arn']:
                        if arn_key not in cloud_account['auth_secrets']:
                            logger.warning(f"{arn_key} not found for account {account_id}")

                elif auth_type == 'key_pair':
                    for key in ['access_key_id', 'secret_access_key']:
                        if key in cloud_account['auth_secrets']:
                            decrypted_value = self.decrypt_data(cloud_account['auth_secrets'][key])
                            cloud_account['auth_secrets'][key] = decrypted_value
                            logger.info(f"Successfully decrypted {key} for account {account_id}")

                elif auth_type == 'azure_service_principal':
                    # Only decrypt the client secret, leave client_id and tenant_id as-is
                    if 'azure_client_secret' in cloud_account['auth_secrets']:
                        decrypted_value = self.decrypt_data(cloud_account['auth_secrets']['azure_client_secret'])
                        cloud_account['auth_secrets']['azure_client_secret'] = decrypted_value
                        logger.info(f"Successfully decrypted azure_client_secret for account {account_id}")

                elif auth_type == 'gcp_service_account':
                    if 'google_application_credentials' in cloud_account['auth_secrets']:
                        decrypted_value = self.decrypt_data(cloud_account['auth_secrets']['google_application_credentials'])
                        cloud_account['auth_secrets']['google_application_credentials'] = decrypted_value
                        logger.info(f"Successfully decrypted google_application_credentials for account {account_id}")

            # Decrypt all values in the secrets dictionary
            if 'secrets' in cloud_account:
                for key, encrypted_value in cloud_account['secrets'].items():
                    cloud_account['secrets'][key] = self.decrypt_data(encrypted_value)

            logger.debug(cloud_account)
            return True, cloud_account
        except Exception as e:
            logger.error(f"Failed to get cloud account details for project '{project_name}', account '{account_id}': {str(e)}")
            return False, f"Failed to get cloud account details: {str(e)}"

    async def search_cloud_accounts(self, project_name: str, query: str):
        try:
            regex_query = {'$regex': query, '$options': 'i'}
            cloud_accounts = await self.db_manager.find_documents('cloud_accounts', {
                'project_name': project_name,
                '$or': [
                    {'account_id': regex_query},
                    {'cloud_platform': regex_query}
                ]
            })

            # Format the results for search
            search_results = [
                {
                    "id": str(account.get("_id")),
                    "account_id": account.get("account_id"),
                    "cloud_platform": account.get("cloud_platform"),
                    "text": f"{account.get('cloud_platform')} - {account.get('account_id')}"
                }
                for account in cloud_accounts
            ]

            return True, search_results
        except Exception as e:
            logger.error(f"Failed to search cloud accounts for project '{project_name}': {str(e)}")
            return False, []
