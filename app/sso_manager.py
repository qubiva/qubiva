# app/sso_manager.py
import logging
import re
from typing import Dict, Tuple, Optional
from datetime import datetime
from onelogin.saml2.auth import OneLogin_Saml2_Auth
import os
from app.app_config_manager import ConfigManager

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class SSOManager:
    """
    Manages SAML 2.0 SSO authentication.
    Handles SAML requests, responses, and session validation.
    """

    def __init__(self, db_manager, kms_manager, project_manager):
        self.db_manager = db_manager
        self.kms_manager = kms_manager
        self.project_manager = project_manager

    @property
    def domain(self):
        """Get app base URL from config, falling back to DOMAIN env var."""
        url = ConfigManager.get_config('app', 'base_url')
        if url:
            return url.rstrip('/')
        domain_env = os.getenv('DOMAIN')
        if domain_env:
            return f"https://{domain_env}"
        return None

    async def get_sso_config(self) -> Optional[Dict]:
        """
        Get SSO configuration from org_settings.
        Returns None if SSO is not configured or disabled.
        """
        try:
            sso_config = await self.db_manager.find_document(
                'org_settings',
                {'setting_type': 'sso'}
            )

            if not sso_config or not sso_config.get('enabled', False):
                return None

            return sso_config
        except Exception as e:
            logger.error(f"Failed to get SSO config: {str(e)}")
            return None

    async def is_sso_enabled(self) -> bool:
        """Check if SSO is enabled for the organization."""
        config = await self.get_sso_config()
        return config is not None and config.get('enabled', False)

    def prepare_saml_request(self, request_data: Dict, sso_config: Dict) -> Dict:
        """
        Prepare SAML authentication request.

        Args:
            request_data: FastAPI request data formatted for OneLogin SAML

        Returns:
            Dictionary containing SAML auth object and redirect URL
        """
        try:
            saml_auth = OneLogin_Saml2_Auth(request_data, self._get_saml_settings(sso_config))
            sso_url = saml_auth.login()

            return {
                'success': True,
                'sso_url': sso_url,
                'auth': saml_auth
            }
        except Exception as e:
            logger.error(f"Failed to prepare SAML request: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    async def process_saml_response(self, request_data: Dict, sso_config: Dict) -> Tuple[bool, str, Optional[Dict]]:
        """
        Process and validate SAML response from IdP.

        Args:
            request_data: FastAPI request data formatted for OneLogin SAML
            sso_config: SSO configuration from database

        Returns:
            Tuple of (success, message, user_data)
            user_data contains: email, saml_groups, name_id
        """
        try:
            saml_auth = OneLogin_Saml2_Auth(request_data, self._get_saml_settings(sso_config))
            logger.info("Processing SAML response...")
            logger.debug(f"Request data keys: {list(request_data.keys())}")
            logger.debug(f"Post data keys: {list(request_data.get('post_data', {}).keys())}")
            saml_auth.process_response()

            errors = saml_auth.get_errors()
            if errors:
                logger.error(f"SAML errors: {errors}")
                error_reason = saml_auth.get_last_error_reason()
                logger.error(f"SAML error reason: {error_reason}")
                logger.error(f"Expected Entity ID: {sso_config.get('saml_idp_entity_id')}")
                logger.error(f"Expected ACS URL: {self.domain}/api/v1/sso/acs")
                return False, f"SAML authentication failed: {', '.join(errors)}", None

            if not saml_auth.is_authenticated():
                return False, "SAML authentication failed: Not authenticated", None

            # Extract user attributes
            attributes = saml_auth.get_attributes()
            name_id = saml_auth.get_nameid()

            # NEW: Universal email extraction
            email = self._extract_email_from_saml(attributes, name_id, sso_config)
            if email:
                email = email.strip().lower()

            if not email:
                logger.error(f"Failed to extract email. Attributes: {list(attributes.keys())}, NameID: {name_id}")
                return False, "SAML response does not contain a valid email address", None

            # Get groups from SAML attributes (if configured)
            groups_attribute = sso_config.get('attribute_mapping', {}).get('groups')
            saml_groups = []
            if groups_attribute:
                raw_groups = self._extract_attribute_list(attributes, groups_attribute)
                # Filter: only strings, max 200 chars each
                saml_groups = [
                    g for g in raw_groups
                    if isinstance(g, str) and len(g) <= 200
                ]

            # Check access control
            access_granted = self._check_access_control(
                sso_config=sso_config,
                email=email,
                saml_groups=saml_groups
            )

            if not access_granted:
                logger.warning(f"SSO access denied for {email}. Not in allowed groups.")
                return False, "Access denied. You are not authorized to access this application.", None

            user_data = {
                'email': email,
                'saml_groups': saml_groups,
                'name_id': name_id
            }

            logger.info(f"SSO login successful for user: {email}")
            return True, "SAML authentication successful", user_data

        except Exception as e:
            logger.error(f"Failed to process SAML response: {str(e)}")
            return False, f"SAML processing failed: {str(e)}", None

    def _extract_email_from_saml(self, attributes: Dict, name_id: str, sso_config: Dict) -> Optional[str]:
        """
        NEW: Universal email extraction that works with all enterprise IdPs.

        Priority order:
        1. Custom email attribute (if configured by admin)
        2. Standard SAML email claim URIs (Azure AD, Okta, Google, LDAP)
        3. NameID if it's already a valid email
        4. Azure AD guest format cleanup (#EXT# format)

        Args:
            attributes: SAML attributes dictionary
            name_id: SAML NameID value
            sso_config: SSO configuration

        Returns:
            Email address string or None if extraction fails
        """
        # Priority 1: Try custom email attribute if configured
        custom_email_attr = sso_config.get('attribute_mapping', {}).get('email')
        if custom_email_attr and custom_email_attr != 'email':
            email = self._extract_attribute(attributes, custom_email_attr)
            if email and self._is_valid_email(email):
                logger.debug(f"Extracted email from custom attribute '{custom_email_attr}': {email}")
                return email

        # Priority 2: Try standard SAML email claim URIs
        standard_email_claims = [
            'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress',  # Microsoft/ADFS
            'email',                                                                # Okta/Google/OneLogin
            'emailAddress',                                                         # Alternative
            'mail',                                                                 # LDAP-style
            'urn:oid:0.9.2342.19200300.100.1.3',                                   # LDAP OID
        ]

        for claim in standard_email_claims:
            email = self._extract_attribute(attributes, claim)
            if email and self._is_valid_email(email):
                logger.debug(f"Extracted email from standard claim '{claim}': {email}")
                return email

        # Priority 3: Try NameID if it's already a valid email
        if name_id and self._is_valid_email(name_id):
            logger.debug(f"Using NameID as email: {name_id}")
            return name_id

        # Priority 4: Try Azure AD guest email cleanup
        if name_id and '#EXT#' in name_id:
            cleaned_email = self._clean_azure_guest_email(name_id)
            if cleaned_email and self._is_valid_email(cleaned_email):
                logger.debug(f"Cleaned Azure AD guest email from NameID: {cleaned_email}")
                return cleaned_email

        # Failed to extract email
        logger.warning(f"Could not extract email from SAML response. Available attributes: {list(attributes.keys())}")
        logger.warning(f"NameID value: {name_id}")
        return None

    def _is_valid_email(self, email: str) -> bool:
        """Validate that extracted value is actually an email address."""
        if not email or not isinstance(email, str):
            return False

        email = email.strip()
        # Basic email regex: username@domain.tld
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            return False

        # Reject suspicious patterns
        local, domain = email.rsplit('@', 1)
        if '..' in local or local.startswith('.') or domain.startswith('.'):
            return False

        return True

    def _clean_azure_guest_email(self, azure_format: str) -> Optional[str]:
        """
        NEW: Convert Azure AD external user format to clean email.

        Converts: user_domain.com#EXT#@tenant.onmicrosoft.com
        To: user@domain.com

        Args:
            azure_format: Azure AD guest user format string

        Returns:
            Cleaned email address or None if format doesn't match
        """
        if not azure_format or '#EXT#' not in azure_format:
            return None

        try:
            # Extract part before #EXT#
            before_ext = azure_format.split('#EXT#')[0]  # "user_domain.com"

            # Use rsplit to handle usernames containing underscores
            # e.g. "john_doe_domain.com" -> "john_doe" + "domain.com"
            parts = before_ext.rsplit('_', 1)
            if len(parts) != 2:
                return None
            cleaned = f"{parts[0]}@{parts[1]}"

            # Validate the result before returning
            if not self._is_valid_email(cleaned):
                return None

            return cleaned
        except Exception as e:
            logger.error(f"Failed to clean Azure guest email '{azure_format}': {e}")
            return None

    def _extract_attribute(self, attributes: Dict, attribute_name: str, default: str = None) -> Optional[str]:
        """Extract single attribute value from SAML attributes."""
        if not attribute_name or not attributes:
            return default

        attr_value = attributes.get(attribute_name, [])
        if isinstance(attr_value, list) and len(attr_value) > 0:
            return attr_value[0]
        elif isinstance(attr_value, str):
            return attr_value
        return default

    def _extract_attribute_list(self, attributes: Dict, attribute_name: str) -> list:
        """Extract list of values from SAML attributes."""
        if not attribute_name or not attributes:
            return []

        attr_value = attributes.get(attribute_name, [])
        if isinstance(attr_value, list):
            return attr_value
        elif isinstance(attr_value, str):
            return [attr_value]
        return []

    def _check_access_control(self, sso_config: Dict, email: str, saml_groups: list) -> bool:
        """
        Check if user should be granted access based on access control rules.

        Returns:
            True if access should be granted, False otherwise
        """
        access_control = sso_config.get('access_control', {})
        mode = access_control.get('mode', 'open')

        if mode == 'open':
            return True

        if mode == 'email_domain':
            allowed_domains = access_control.get('allowed_domains', [])
            if not allowed_domains:
                return True

            email_domain = email.split('@')[1] if '@' in email else ''
            return email_domain in allowed_domains

        if mode == 'group_whitelist':
            allowed_groups = access_control.get('allowed_groups', [])
            if not allowed_groups:
                return True

            # Check if user has ANY allowed group
            return any(group in allowed_groups for group in saml_groups)

        return False  # Default deny

    def determine_org_roles(self, sso_config: Dict, saml_groups: list) -> list:
        """
        FIXED: Determine organization roles based on SAML groups and role mapping.
        Now allows empty default roles.

        Returns:
            List of org_roles to assign to the user (can be empty)
        """
        # FIXED: Get default roles (can be empty list)
        default_roles = sso_config.get('default_org_roles', [])

        # FIXED: If explicitly set to empty, return empty (don't force org_viewer)
        if default_roles == []:
            # Check if group mapping will provide roles
            if not sso_config.get('group_mapping_enabled', False):
                return []  # No default roles and no group mapping = empty roles

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

    def _get_saml_settings(self, sso_config: Dict = None) -> Dict:
        """
        Build SAML settings dictionary for OneLogin library.

        Args:
            sso_config: SSO configuration from database
        """
        if not sso_config:
            raise ValueError("SSO configuration required")

        logger.debug(f"Building SAML settings for domain: {self.domain}")
        logger.debug(f"IdP Entity ID: {sso_config.get('saml_idp_entity_id')}")
        logger.debug(f"IdP SSO URL: {sso_config.get('saml_idp_sso_url')}")
        logger.debug(f"IdP Cert present: {bool(sso_config.get('saml_idp_cert'))}")

        # Build SAML settings
        settings = {
            'strict': True,
            'debug': os.getenv('SAML_DEBUG', 'false').lower() == 'true',
            'sp': {
                'entityId': self.domain,
                'assertionConsumerService': {
                    'url': f'{self.domain}/api/v1/sso/acs',
                    'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST'
                },
                'singleLogoutService': {
                    'url': f'{self.domain}/api/v1/sso/sls',
                    'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect'
                },
                'NameIDFormat': 'urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress'
            },
            'idp': {
                'entityId': sso_config.get('saml_idp_entity_id', ''),
                'singleSignOnService': {
                    'url': sso_config.get('saml_idp_sso_url', ''),
                    'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect'
                },
                'x509cert': sso_config.get('saml_idp_cert', '')
            }
        }

        # Only add IdP SLO service if URL is provided (it's optional)
        slo_url = sso_config.get('saml_idp_slo_url')
        if slo_url:
            settings['idp']['singleLogoutService'] = {
                'url': slo_url,
                'binding': 'urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect'
            }

        return settings

    async def create_sso_session(self, email: str) -> str:
        """
        Create a session token for SSO user.
        Uses existing KMS JWT infrastructure.

        Returns:
            JWT session token
        """
        # Create JWT with 1 hour expiry (same as existing local auth)
        token = self.kms_manager.create_jwt(
            subject=email,
            expiry_hours=1,
            additional_claims={'auth_method': 'sso'}
        )
        return token

    async def validate_sso_session(self, token: str) -> Optional[Dict]:
        """
        Validate SSO session token.

        Returns:
            User dict if valid, None if invalid
        """
        try:
            payload = self.kms_manager.verify_jwt(token)

            # Check if it's an SSO token
            if payload.get('auth_method') != 'sso':
                return None

            username = payload.get('sub')
            if not username:
                return None

            # Get user from database
            user = await self.db_manager.find_document('users', {'username': username})

            # Check if user is active
            if user and not user.get('active', True):
                logger.warning(f"Blocked login attempt by deactivated SSO user: {username}")
                return None

            return user

        except Exception as e:
            logger.debug(f"SSO session validation failed: {str(e)}")
            return None

    async def auto_provision_user(self, email: str, saml_groups: list, sso_config: Dict) -> Tuple[bool, str]:
        """
        Auto-provision a new SSO user.

        Args:
            email: User's email address
            saml_groups: Groups from SAML assertion
            sso_config: SSO configuration

        Returns:
            Tuple of (success, message)
        """
        try:
            # Safety limit: prevent unbounded user provisioning
            max_provisioned = sso_config.get('max_auto_provisioned_users', 500)
            current_count = await self.db_manager.count_documents(
                'users', {'auto_provisioned': True}
            )
            if current_count >= max_provisioned:
                logger.warning(f"Auto-provisioning limit reached ({max_provisioned}). Denying {email}")
                return False, "Auto-provisioning limit reached. Contact your administrator."

            # Determine org roles
            org_roles = self.determine_org_roles(sso_config, saml_groups)

            # Create user data
            user_data = {
                'username': email,
                'hashed_password': None,  # SSO users don't have passwords
                'projects': [],
                'org_roles': org_roles,
                'auth_method': 'sso',
                'saml_groups': saml_groups,
                'created_at': datetime.utcnow(),
                'last_login': datetime.utcnow(),
                'auto_provisioned': True,
                'active': True
            }

            await self.db_manager.insert_document('users', user_data)

            logger.info(f"Auto-provisioned SSO user: {email} with roles {org_roles}")
            return True, f"User {email} auto-provisioned via SSO"

        except Exception as e:
            logger.error(f"Failed to auto-provision SSO user {email}: {str(e)}")
            return False, f"Failed to auto-provision user: {str(e)}"

    async def deactivate_user(self, username: str, reason: str) -> Tuple[bool, str]:
        """
        Deactivate a user (soft delete).

        Args:
            username: User's email/username
            reason: Reason for deactivation

        Returns:
            Tuple of (success, message)
        """
        try:
            update_result = await self.db_manager.update_one_document(
                'users',
                {'username': username},
                {
                    '$set': {
                        'active': False,
                        'deactivated_at': datetime.utcnow(),
                        'deactivation_reason': reason
                    }
                }
            )

            if update_result['matched_count'] > 0:
                # Log to audit trail (optional)
                logger.info(f"Deactivated user: {username}. Reason: {reason}")
                return True, f"User {username} deactivated successfully"
            else:
                return False, f"User {username} not found"

        except Exception as e:
            logger.error(f"Failed to deactivate user {username}: {str(e)}")
            return False, f"Failed to deactivate user: {str(e)}"
