from typing import List, Set
import fnmatch
import logging

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class RBAC:
    def __init__(self, config_manager):
        self.config_manager = config_manager

    def _get_permissions(self):
        permissions = self.config_manager.get_config('roles_and_permissions')
        if not permissions:
            raise ValueError("Failed to load permissions from config")
        return permissions

    def check_permissions(self, required_permissions: List[str], project_roles: List[str], org_roles: List[str]) -> bool:
        user_permissions = self._get_user_permissions(org_roles, project_roles)

        logger.debug(f"Required permissions: {required_permissions}")
        logger.debug(f"User permissions: {user_permissions}")

        for required_permission in required_permissions:
            if not any(fnmatch.fnmatch(required_permission, user_perm) for user_perm in user_permissions):
                if not any(fnmatch.fnmatch(user_perm, required_permission) for user_perm in user_permissions):
                    logger.debug(f"Permission check failed for: {required_permission}")
                    return False, user_permissions
        return True, list(user_permissions)

    def _get_user_permissions(self, org_roles: List[str], project_roles: List[str]) -> Set[str]:
        permissions = set()
        perms_config = self._get_permissions()

        for role in org_roles:
            org_perms = perms_config['organization'].get(role, [])
            if '*' in org_perms:
                return {'*'}
            permissions.update(org_perms)

        for role in project_roles:
            permissions.update(perms_config['project'].get(role, []))

        logger.debug(f"Final permissions: {permissions}")
        return permissions

    def get_all_project_roles(self) -> List[str]:
        return list(self._get_permissions()['project'].keys())

    def get_all_org_roles(self) -> List[str]:
        return list(self._get_permissions()['organization'].keys())
