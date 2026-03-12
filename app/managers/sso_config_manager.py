import logging
import traceback
import socket
import ipaddress
import requests
import defusedxml.ElementTree as ET
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from urllib.parse import urlparse
from app.managers.base import ManagerBase

logger = logging.getLogger('uvicorn.error')


class SSOConfigManager(ManagerBase):
    def __init__(self, db_manager, kms_manager, rbac):
        super().__init__(db_manager, kms_manager)
        self.rbac = rbac

    async def get_sso_config(self) -> Tuple[bool, Optional[Dict]]:
        """
        Get SSO configuration from org_settings.
        Returns (True, config_dict) if SSO is configured, (True, None) if not configured.
        """
        try:
            sso_config = await self.db_manager.find_document(
                'org_settings',
                {'setting_type': 'sso'}
            )

            if not sso_config:
                return True, None

            # Remove _id field
            sso_config.pop('_id', None)

            return True, sso_config

        except Exception as e:
            logger.error(f"Failed to get SSO config: {str(e)}")
            return False, f"Failed to get SSO config: {str(e)}"

    async def update_sso_config(
        self,
        enabled: bool,
        saml_idp_metadata_url: Optional[str] = None,
        saml_idp_entity_id: Optional[str] = None,
        saml_idp_sso_url: Optional[str] = None,
        saml_idp_slo_url: Optional[str] = None,
        saml_idp_cert: Optional[str] = None,
        access_control: Optional[Dict] = None,
        attribute_mapping: Optional[Dict] = None,
        default_org_roles: Optional[List[str]] = None,
        group_mapping_enabled: bool = False,
        group_mapping: Optional[Dict] = None,
        auto_provision: bool = True
    ) -> Tuple[bool, str]:
        try:
            # Validate: Must provide either metadata URL OR manual config
            if not saml_idp_metadata_url:
                if not all([saml_idp_entity_id, saml_idp_sso_url, saml_idp_cert]):
                    return False, "Must provide either saml_idp_metadata_url OR (saml_idp_entity_id, saml_idp_sso_url, saml_idp_cert)"

            valid_roles = set(self.rbac.get_all_org_roles())

            # default_org_roles: allow None or [], but if provided, it must be a list of valid roles
            if default_org_roles is not None:
                if not isinstance(default_org_roles, list):
                    return False, "default_org_roles must be a list"
                bad = [r for r in default_org_roles if r not in valid_roles]
                if bad:
                    return False, f"Invalid default_org_roles: {bad}"

            # group_mapping: when enabled, must be a dict[str, list[str]] with only valid roles
            clean_group_mapping = None
            if group_mapping_enabled:
                if group_mapping:
                    if not isinstance(group_mapping, dict):
                        return False, "group_mapping must be an object (dict of group -> roles)"
                    tmp = {}
                    for g, roles in group_mapping.items():
                        roles_list = roles if isinstance(roles, list) else [roles]
                        bad = [r for r in roles_list if r not in valid_roles]
                        if bad:
                            return False, f"Invalid roles in group_mapping for '{g}': {bad}"
                        if roles_list:
                            tmp[g] = roles_list
                    clean_group_mapping = tmp
                else:
                    clean_group_mapping = {}

            # Build SSO config document
            sso_config = {
                'setting_type': 'sso',
                'enabled': enabled,
                'auto_provision': auto_provision,
                'default_org_roles': default_org_roles or [],
                'group_mapping_enabled': group_mapping_enabled,
                'updated_at': datetime.utcnow()
            }

            if group_mapping_enabled and clean_group_mapping:
                sso_config['group_mapping'] = clean_group_mapping

            # Add SAML IdP configuration
            if saml_idp_metadata_url:
                sso_config['saml_idp_metadata_url'] = saml_idp_metadata_url

                # Try to parse metadata with proper error handling
                try:
                    logger.info(f"Attempting to parse IdP metadata from: {saml_idp_metadata_url}")
                    parsed_metadata = await self._parse_idp_metadata(saml_idp_metadata_url)

                    # Store parsed values
                    sso_config['saml_idp_entity_id'] = parsed_metadata['entity_id']
                    sso_config['saml_idp_sso_url'] = parsed_metadata['sso_url']
                    sso_config['saml_idp_slo_url'] = parsed_metadata.get('slo_url')
                    sso_config['saml_idp_cert'] = parsed_metadata['x509cert']

                    logger.info("Successfully parsed IdP metadata")

                except Exception as metadata_error:
                    error_msg = f"Failed to parse IdP metadata: {str(metadata_error)}"
                    logger.error(error_msg)
                    logger.error(traceback.format_exc())

                    # Return error instead of saving incomplete config
                    return False, f"Metadata parsing failed: {str(metadata_error)}. Please verify the metadata URL is correct and accessible."
            else:
                # Manual configuration
                sso_config['saml_idp_entity_id'] = saml_idp_entity_id
                sso_config['saml_idp_sso_url'] = saml_idp_sso_url
                sso_config['saml_idp_cert'] = saml_idp_cert
                if saml_idp_slo_url:
                    sso_config['saml_idp_slo_url'] = saml_idp_slo_url

            # NEW: Validate required fields are present before enabling
            if enabled:
                required_fields = ['saml_idp_entity_id', 'saml_idp_sso_url', 'saml_idp_cert']
                missing_fields = [field for field in required_fields if not sso_config.get(field)]

                if missing_fields:
                    error_msg = f"Cannot enable SSO with incomplete configuration. Missing: {', '.join(missing_fields)}"
                    logger.error(error_msg)
                    return False, error_msg

            # Add access control
            if access_control:
                sso_config['access_control'] = access_control
            else:
                sso_config['access_control'] = {'mode': 'open'}

            # Add attribute mapping
            if attribute_mapping:
                sso_config['attribute_mapping'] = attribute_mapping
            else:
                sso_config['attribute_mapping'] = {
                    'email': 'email',
                    'groups': 'groups'
                }

            update_doc = {
                '$set': sso_config,
                '$setOnInsert': {'created_at': datetime.utcnow()}
            }

            if (not group_mapping_enabled) or (group_mapping_enabled and clean_group_mapping == {}):
                update_doc['$unset'] = {'group_mapping': ""}

            await self.db_manager.update_one_document(
                'org_settings',
                {'setting_type': 'sso'},
                update_doc,
                upsert=True
            )
            logger.info(f"SSO config updated successfully. Enabled: {enabled}")
            return True, "SSO configuration updated successfully"

        except Exception as e:
            logger.error(f"Failed to update SSO config: {str(e)}")
            logger.error(traceback.format_exc())
            return False, f"Failed to update SSO config: {str(e)}"

    async def _parse_idp_metadata(self, metadata_url: str) -> Dict:
        """
        Fetch and parse SAML IdP metadata XML from URL.
        Returns dict with entityId, sso_url, slo_url, x509cert.
        """
        try:
            # Validate metadata URL: enforce HTTPS and reject private IPs (SSRF prevention)
            parsed_url = urlparse(metadata_url)
            if parsed_url.scheme != 'https':
                raise ValueError("Metadata URL must use HTTPS")
            hostname = parsed_url.hostname
            if not hostname:
                raise ValueError("Invalid metadata URL")
            try:
                resolved_ips = socket.getaddrinfo(hostname, None)
                for _, _, _, _, sockaddr in resolved_ips:
                    ip = ipaddress.ip_address(sockaddr[0])
                    if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                        raise ValueError("Metadata URL resolves to a private/reserved IP address")
            except socket.gaierror:
                raise ValueError(f"Cannot resolve hostname: {hostname}")

            # Fetch metadata XML
            response = requests.get(metadata_url, timeout=10, allow_redirects=False)
            response.raise_for_status()

            # Add debug logging
            logger.info(f"Successfully fetched metadata from {metadata_url}")
            logger.debug(f"Metadata content length: {len(response.content)} bytes")

            # Parse XML
            root = ET.fromstring(response.content)

            # Define namespaces
            ns = {
                'md': 'urn:oasis:names:tc:SAML:2.0:metadata',
                'ds': 'http://www.w3.org/2000/09/xmldsig#'
            }

            # Extract IdP descriptor
            idp_descriptor = root.find('.//md:IDPSSODescriptor', ns)
            if not idp_descriptor:
                raise ValueError("No IDPSSODescriptor found in metadata")

            # Extract entity ID
            entity_id = root.get('entityID')

            # Extract SSO URL (HTTP-Redirect binding) - REQUIRED
            sso_service = idp_descriptor.find(".//md:SingleSignOnService[@Binding='urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect']", ns)
            sso_url = sso_service.get('Location') if sso_service is not None else None

            # Extract SLO URL (optional) - Initialize to None first
            slo_url = None
            slo_service = idp_descriptor.find(".//md:SingleLogoutService[@Binding='urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect']", ns)
            if slo_service is not None:
                slo_url = slo_service.get('Location')

            # Extract X509 certificate - REQUIRED
            cert_element = idp_descriptor.find('.//ds:X509Certificate', ns)
            x509cert = cert_element.text.strip() if cert_element is not None else None

            # Add detailed validation logging
            logger.info(f"Parsed metadata - Entity ID present: {bool(entity_id)}, SSO URL present: {bool(sso_url)}, SLO URL present: {bool(slo_url)}, Cert present: {bool(x509cert)}")

            # Validate REQUIRED fields only (entity_id, sso_url, x509cert)
            # slo_url is optional
            if not all([entity_id, sso_url, x509cert]):
                missing = []
                if not entity_id:
                    missing.append("entityID")
                if not sso_url:
                    missing.append("SSO URL")
                if not x509cert:
                    missing.append("X509 certificate")
                error_msg = f"Missing required metadata fields: {', '.join(missing)}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            # Log if SLO URL is missing (informational, not an error)
            if not slo_url:
                logger.info("SLO URL not found in metadata - Single Logout will not be available")

            return {
                'entity_id': entity_id,
                'sso_url': sso_url,
                'slo_url': slo_url,  # Can be None - this is OK
                'x509cert': x509cert
            }

        except Exception as e:
            logger.error(f"Failed to parse IdP metadata: {str(e)}")
            raise

    async def delete_sso_config(self) -> Tuple[bool, str]:
        """
        Delete SSO configuration from org_settings.
        WARNING: This will disable SSO for all users.

        Returns:
            Tuple of (success, message)
        """
        try:
            result = await self.db_manager.delete_document(
                'org_settings',
                {'setting_type': 'sso'}
            )

            if result > 0:
                logger.info("SSO configuration deleted successfully")
                return True, "SSO configuration deleted successfully. SSO users will no longer be able to login."
            else:
                return False, "SSO configuration not found"

        except Exception as e:
            logger.error(f"Failed to delete SSO config: {str(e)}")
            return False, f"Failed to delete SSO config: {str(e)}"

    async def update_sso_user_roles_on_login(self, username: str, saml_groups: List[str]) -> Tuple[bool, str]:
        """
        Update SSO user's roles based on current SAML groups.
        Now:
        - Only rewrites org_roles when group mapping is enabled.
        - Filters out any non-existent roles before writing.
        """
        try:
            # Get SSO config
            success, sso_config = await self.get_sso_config()
            if not success or not sso_config:
                return False, "SSO not configured"

            # If group mapping is NOT enabled, do NOT touch org_roles; just update telemetry
            if not sso_config.get('group_mapping_enabled', False):
                update_result = await self.db_manager.update_one_document(
                    'users',
                    {'username': username},
                    {'$set': {'saml_groups': saml_groups, 'last_login': datetime.utcnow()}}
                )
                if update_result['matched_count'] > 0:
                    return True, "Skipped role sync (group mapping disabled)"
                return False, f"User {username} not found"

            # Compute roles via mapping/defaults
            new_roles = self._determine_org_roles_from_groups(sso_config, saml_groups) or []

            # FINAL SAFETY: keep only valid roles
            valid_roles = set(self.rbac.get_all_org_roles())
            new_roles = [r for r in new_roles if r in valid_roles]

            update_result = await self.db_manager.update_one_document(
                'users',
                {'username': username},
                {
                    '$set': {
                        'org_roles': new_roles,
                        'saml_groups': saml_groups,
                        'last_login': datetime.utcnow()
                    }
                }
            )

            if update_result['matched_count'] > 0:
                logger.info(f"Updated SSO user {username} roles to {new_roles} based on groups {saml_groups}")
                return True, f"User roles updated to {new_roles}"
            else:
                return False, f"User {username} not found"

        except Exception as e:
            logger.error(f"Failed to update SSO user roles: {str(e)}")
            return False, f"Failed to update user roles: {str(e)}"

    def _determine_org_roles_from_groups(self, sso_config: Dict, saml_groups: List[str]) -> List[str]:
        """
        Internal helper to determine org roles from SAML groups.

        Args:
            sso_config: SSO configuration
            saml_groups: SAML groups from IdP

        Returns:
            List of org_roles
        """
        # Default roles
        default_roles = sso_config.get('default_org_roles', [])

        # Check if group mapping is enabled
        if not sso_config.get('group_mapping_enabled', False):
            return default_roles

        # Get group mapping
        group_mapping = sso_config.get('group_mapping', {})
        if not group_mapping:
            return default_roles

        # Map SAML groups to org roles
        mapped_roles = []
        for saml_group in saml_groups:
            if saml_group in group_mapping:
                roles = group_mapping[saml_group]
                if isinstance(roles, list):
                    mapped_roles.extend(roles)
                elif isinstance(roles, str):
                    mapped_roles.append(roles)

        # Return mapped roles if any, otherwise default
        return list(set(mapped_roles)) if mapped_roles else default_roles
