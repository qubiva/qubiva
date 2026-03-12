import logging
from typing import Tuple
from app.managers.base import ManagerBase

logger = logging.getLogger('uvicorn.error')


class CredentialManager(ManagerBase):
    def __init__(self, db_manager, kms_manager):
        super().__init__(db_manager, kms_manager)

    async def _resolve_credential_reference(self, project_name: str, credential_name: str):
        """
        Internal method to resolve a credential reference to actual auth_secrets.
        This is used internally to maintain backward compatibility.
        """
        try:
            logger.debug(f"RESOLVING CREDENTIAL: project={project_name}, credential={credential_name}")

            credential = await self.db_manager.find_document(
                'credentials',
                {'project_name': project_name, 'credential_name': credential_name}
            )
            if not credential:
                raise ValueError(f"Credential '{credential_name}' not found in project '{project_name}'")

            logger.debug(f"FOUND CREDENTIAL DOCUMENT: {credential}")

            # Decrypt the credential's auth_secrets based on type
            auth_secrets = credential.get('auth_secrets', {})
            auth_type = auth_secrets.get('type')

            logger.debug(f"AUTH_SECRETS BEFORE DECRYPTION: {auth_secrets}")
            logger.debug(f"AUTH_TYPE: {auth_type}")

            if auth_type == 'external_certificate_authority':
                for key in ['certificate', 'key']:
                    if key in auth_secrets:
                        logger.debug(f"DECRYPTING {key} for external_certificate_authority")
                        auth_secrets[key] = self.decrypt_data(auth_secrets[key])
            elif auth_type == 'key_pair':
                for key in ['access_key_id', 'secret_access_key']:
                    if key in auth_secrets:
                        logger.debug(f"DECRYPTING {key} for key_pair")
                        decrypted_value = self.decrypt_data(auth_secrets[key])
                        logger.debug(f"DECRYPTED {key}: {decrypted_value[:10]}..." if decrypted_value else f"DECRYPTED {key}: EMPTY")
                        auth_secrets[key] = decrypted_value
            elif auth_type == 'azure_service_principal':
                if 'azure_client_secret' in auth_secrets:
                    logger.debug("DECRYPTING azure_client_secret for azure_service_principal")
                    auth_secrets['azure_client_secret'] = self.decrypt_data(auth_secrets['azure_client_secret'])
            elif auth_type == 'gcp_service_account':
                if 'google_application_credentials' in auth_secrets:
                    logger.debug("DECRYPTING google_application_credentials for gcp_service_account")
                    auth_secrets['google_application_credentials'] = self.decrypt_data(auth_secrets['google_application_credentials'])

            logger.debug(f"FINAL AUTH_SECRETS AFTER DECRYPTION: {auth_secrets}")
            return auth_secrets
        except Exception as e:
            logger.error(f"Failed to resolve credential reference '{credential_name}': {str(e)}")
            raise

    async def create_credential(self, project_name: str, credential_data: dict, acting_user: str = None) -> Tuple[bool, str]:
        """Create a new credential for the project."""
        try:
            # Check if credential name already exists
            existing = await self.db_manager.find_document(
                'credentials',
                {'project_name': project_name, 'credential_name': credential_data['credential_name']}
            )
            if existing:
                return False, f"Credential '{credential_data['credential_name']}' already exists"

            # Map credential types to cloud platforms
            platform_map = {
                'external_certificate_authority': 'aws',
                'key_pair': 'aws',
                'azure_service_principal': 'azure',
                'gcp_service_account': 'gcp'
            }

            credential_type = credential_data.get('credential_type', 'external_certificate_authority')
            cloud_platform = platform_map.get(credential_type, 'unknown')

            # Prepare credential document
            credential_doc = {
                'project_name': project_name,
                'credential_name': credential_data['credential_name'],
                'credential_type': credential_type,
                'cloud_platform': cloud_platform,
                'auth_secrets': credential_data['auth_secrets'].copy(),
                **self._audit_create(acting_user),
            }

            # Encrypt sensitive fields based on auth type
            auth_type = credential_doc['auth_secrets'].get('type')

            if auth_type == 'external_certificate_authority':
                for key in ['certificate', 'key']:
                    if key in credential_doc['auth_secrets']:
                        credential_doc['auth_secrets'][key] = self.encrypt_data(credential_doc['auth_secrets'][key])
            elif auth_type == 'key_pair':
                for key in ['access_key_id', 'secret_access_key']:
                    if key in credential_doc['auth_secrets']:
                        credential_doc['auth_secrets'][key] = self.encrypt_data(credential_doc['auth_secrets'][key])
            elif auth_type == 'azure_service_principal':
                if 'azure_client_secret' in credential_doc['auth_secrets']:
                    credential_doc['auth_secrets']['azure_client_secret'] = self.encrypt_data(credential_doc['auth_secrets']['azure_client_secret'])
            elif auth_type == 'gcp_service_account':
                if 'google_application_credentials' in credential_doc['auth_secrets']:
                    credential_doc['auth_secrets']['google_application_credentials'] = self.encrypt_data(credential_doc['auth_secrets']['google_application_credentials'])

            await self.db_manager.insert_document('credentials', credential_doc)
            return True, "Credential created successfully"

        except Exception as e:
            logger.error(f"Failed to create credential: {str(e)}")
            return False, f"Failed to create credential: {str(e)}"

    async def get_credentials_by_project(self, project_name: str):
        """Get all credentials for a project (without decrypted secrets)."""
        try:
            credentials = await self.db_manager.find_documents(
                'credentials',
                {'project_name': project_name}
            )

            # Remove sensitive data for listing
            safe_credentials = []
            for cred in credentials:
                safe_cred = {
                    'credential_name': cred['credential_name'],
                    'credential_type': cred['credential_type'],
                    'created_at': cred.get('created_at'),
                    'updated_at': cred.get('updated_at')
                }
                safe_credentials.append(safe_cred)

            return True, safe_credentials
        except Exception as e:
            logger.error(f"Failed to get credentials: {str(e)}")
            return False, f"Failed to get credentials: {str(e)}"

    async def get_credential_details(self, project_name: str, credential_name: str):
        """Get credential details with decrypted secrets."""
        try:
            credential = await self.db_manager.find_document(
                'credentials',
                {'project_name': project_name, 'credential_name': credential_name}
            )
            if not credential:
                return False, "Credential not found"

            # Decrypt auth_secrets based on type
            auth_type = credential['auth_secrets'].get('type')

            if auth_type == 'external_certificate_authority':
                for key in ['certificate', 'key']:
                    if key in credential['auth_secrets']:
                        credential['auth_secrets'][key] = self.decrypt_data(credential['auth_secrets'][key])
            elif auth_type == 'key_pair':
                for key in ['access_key_id', 'secret_access_key']:
                    if key in credential['auth_secrets']:
                        credential['auth_secrets'][key] = self.decrypt_data(credential['auth_secrets'][key])
            elif auth_type == 'azure_service_principal':
                if 'azure_client_secret' in credential['auth_secrets']:
                    credential['auth_secrets']['azure_client_secret'] = self.decrypt_data(credential['auth_secrets']['azure_client_secret'])
            elif auth_type == 'gcp_service_account':
                if 'google_application_credentials' in credential['auth_secrets']:
                    credential['auth_secrets']['google_application_credentials'] = self.decrypt_data(credential['auth_secrets']['google_application_credentials'])

            return True, credential
        except Exception as e:
            logger.error(f"Failed to get credential details: {str(e)}")
            return False, f"Failed to get credential details: {str(e)}"

    async def update_credential(self, project_name: str, credential_name: str, update_data: dict, acting_user: str = None):
        """Update an existing credential."""
        try:
            # Check if credential exists
            existing = await self.db_manager.find_document(
                'credentials',
                {'project_name': project_name, 'credential_name': credential_name}
            )
            if not existing:
                return False, "Credential not found"

            # Prepare update
            auth_secrets = update_data['auth_secrets'].copy()
            auth_type = auth_secrets.get('type')

            # Encrypt sensitive fields based on auth type
            if auth_type == 'external_certificate_authority':
                for key in ['certificate', 'key']:
                    if key in auth_secrets:
                        auth_secrets[key] = self.encrypt_data(auth_secrets[key])
            elif auth_type == 'key_pair':
                for key in ['access_key_id', 'secret_access_key']:
                    if key in auth_secrets:
                        auth_secrets[key] = self.encrypt_data(auth_secrets[key])
            elif auth_type == 'azure_service_principal':
                if 'azure_client_secret' in auth_secrets:
                    auth_secrets['azure_client_secret'] = self.encrypt_data(auth_secrets['azure_client_secret'])
            elif auth_type == 'gcp_service_account':
                if 'google_application_credentials' in auth_secrets:
                    auth_secrets['google_application_credentials'] = self.encrypt_data(auth_secrets['google_application_credentials'])

            result = await self.db_manager.update_one_document(
                'credentials',
                {'project_name': project_name, 'credential_name': credential_name},
                {'$set': {'auth_secrets': auth_secrets, **self._audit_update(acting_user)}}
            )

            if result['modified_count'] > 0:
                return True, "Credential updated successfully"
            return False, "No changes made"

        except Exception as e:
            logger.error(f"Failed to update credential: {str(e)}")
            return False, f"Failed to update credential: {str(e)}"

    async def delete_credential(self, project_name: str, credential_name: str, acting_user: str = None):
        """Delete a credential and automatically update any cloud accounts that reference it."""
        try:
            # Find all cloud accounts that reference this credential
            referenced_accounts = await self.db_manager.find_documents(
                'cloud_accounts',
                {'project_name': project_name, 'credential_reference': credential_name}
            )

            # Update all referencing cloud accounts to remove the credential reference
            if referenced_accounts:
                for account in referenced_accounts:
                    try:
                        update_result = await self.db_manager.update_one_document(
                            'cloud_accounts',
                            {
                                'project_name': project_name,
                                'cloud_platform': account['cloud_platform'],
                                'account_id': account['account_id']
                            },
                            {
                                '$unset': {'credential_reference': ''}
                                # DON'T set auth_secrets - leave the account in "no auth" state
                            }
                        )
                        if update_result['modified_count'] > 0:
                            logger.info(f"Updated cloud account {account['account_id']} to remove credential reference")
                    except Exception as e:
                        logger.error(f"Failed to update cloud account {account['account_id']}: {str(e)}")

            # Delete the credential
            result = await self.db_manager.delete_document(
                'credentials',
                {'project_name': project_name, 'credential_name': credential_name}
            )

            if result > 0:
                affected_accounts = len(referenced_accounts) if referenced_accounts else 0
                if affected_accounts > 0:
                    return True, f"Credential deleted successfully. {affected_accounts} cloud account(s) now need new credentials configured."
                else:
                    return True, "Credential deleted successfully"
            return False, "Credential not found"

        except Exception as e:
            logger.error(f"Failed to delete credential: {str(e)}")
            return False, f"Failed to delete credential: {str(e)}"
