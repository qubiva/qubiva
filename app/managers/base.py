import logging
import os
from datetime import datetime
from app.app_config_manager import ConfigManager

logger = logging.getLogger('uvicorn.error')


class ManagerBase:
    def __init__(self, db_manager, kms_manager=None):
        self.db_manager = db_manager
        self.kms_manager = kms_manager
        self._domain_env = os.getenv("DOMAIN")

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
