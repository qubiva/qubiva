"""
AI Governance Gateway manager.

Sits between Qubiva route handlers and the LiteLLM proxy client.
Reads configuration from ConfigManager, manages client lifecycle, and
adds Qubiva-specific logic: config gating, credential store integration,
model-credential binding for rotation sync, virtual key → owner binding,
and project token management.
"""
import logging
import os
from typing import Dict, List, Optional

from app.ai_gateway.client import AIGatewayClient
from app.app_config_manager import ConfigManager

logger = logging.getLogger("uvicorn.error")


class AIGatewayManager:
    """Lifecycle manager for AIGatewayClient with credential store and RBAC integration."""

    def __init__(self, config_manager: type, db_manager=None, kms_manager=None):
        self._config_manager = config_manager
        self._client: Optional[AIGatewayClient] = None
        self._credential_store = None
        self._key_binding_store = None
        self._project_token_store = None

        if db_manager and kms_manager:
            from app.ai_gateway.credential_store import LLMCredentialStore
            from app.ai_gateway.key_binding_store import KeyBindingStore
            from app.ai_gateway.project_token_store import ProjectTokenStore

            self._credential_store = LLMCredentialStore(db_manager, kms_manager)
            self._key_binding_store = KeyBindingStore(db_manager)
            self._project_token_store = ProjectTokenStore(db_manager, kms_manager)

    def _get_config(self) -> Dict:
        return self._config_manager.get_config("ai_governance") or {}

    def is_enabled(self) -> bool:
        return bool(self._get_config().get("enabled", False))

    def _build_client(self) -> Optional[AIGatewayClient]:
        cfg = self._get_config()
        gateway = cfg.get("gateway", {})
        url = gateway.get("url", "")
        if not url:
            return None
        key_env = gateway.get("master_key_env", "AI_GATEWAY_MASTER_KEY")
        master_key = os.environ.get(key_env, "")
        timeout = int(gateway.get("timeout_seconds", 30))
        return AIGatewayClient(base_url=url, master_key=master_key, timeout=timeout)

    def _client_or_raise(self) -> AIGatewayClient:
        if not self.is_enabled():
            raise RuntimeError("AI Governance Gateway is not enabled")
        if self._client is None or self._client._client is None or self._client._client.is_closed:
            self._client = self._build_client()
        if self._client is None:
            raise RuntimeError("AI Governance Gateway URL is not configured")
        return self._client

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None

    # ------------------------------------------------------------------
    # Health / status
    # ------------------------------------------------------------------

    async def get_status(self) -> Dict:
        cfg = self._get_config()
        if not self.is_enabled():
            return {"enabled": False, "healthy": False}
        try:
            client = self._client_or_raise()
            healthy = await client.health_check()
        except Exception as exc:
            logger.warning("AI gateway health check failed: %s", exc)
            healthy = False
        return {
            "enabled": True,
            "healthy": healthy,
            "gateway_url": cfg.get("gateway", {}).get("url", ""),
        }

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    async def list_models(self) -> List[Dict]:
        return await self._client_or_raise().list_models()

    async def add_model(self, model_params: Dict) -> Dict:
        """Add a model to LiteLLM. Caller supplies litellm_params including api_key."""
        return await self._client_or_raise().add_model(model_params)

    async def add_model_with_credential(
        self,
        model_name: str,
        litellm_params: Dict,
        credential_id: str,
        model_info: Optional[Dict] = None,
    ) -> Dict:
        """Add a model, resolving credential values from Qubiva's credential store.

        Stores a binding so credential rotation can push updated values to
        LiteLLM automatically via sync_credential_to_models().
        """
        if not self._credential_store:
            raise RuntimeError("Credential store is not available")
        credential_values = await self._credential_store.get_credential_values(credential_id)
        if credential_values is None:
            raise ValueError(f"Credential '{credential_id}' not found")

        params = dict(litellm_params)
        params.update(credential_values)

        body: Dict = {"model_name": model_name, "litellm_params": params}
        if model_info:
            body["model_info"] = model_info

        result = await self._client_or_raise().add_model(body)

        # Store binding for rotation support
        litellm_model_id = result.get("model_id") or result.get("id", "")
        if litellm_model_id:
            await self._credential_store.bind_model(
                litellm_model_id=litellm_model_id,
                model_name=model_name,
                credential_id=credential_id,
                litellm_params=litellm_params,
                credential_keys=list(credential_values.keys()),
                model_info=model_info,
            )
        return result

    async def delete_model(self, model_id: str) -> Dict:
        result = await self._client_or_raise().delete_model(model_id)
        if self._credential_store:
            await self._credential_store.unbind_model(model_id)
        return result

    # ------------------------------------------------------------------
    # Credential store
    # ------------------------------------------------------------------

    async def store_credential(
        self, name: str, provider: str, credential_values: dict, acting_user: str
    ) -> str:
        if not self._credential_store:
            raise RuntimeError("Credential store is not available")
        return await self._credential_store.store_credential(name, provider, credential_values, acting_user)

    async def list_credentials(self) -> List[Dict]:
        if not self._credential_store:
            raise RuntimeError("Credential store is not available")
        return await self._credential_store.list_credentials()

    async def get_credential_meta(self, credential_id: str) -> Optional[Dict]:
        if not self._credential_store:
            raise RuntimeError("Credential store is not available")
        return await self._credential_store.get_credential_meta(credential_id)

    async def delete_credential(self, credential_id: str) -> bool:
        if not self._credential_store:
            raise RuntimeError("Credential store is not available")
        return await self._credential_store.delete_credential(credential_id)

    async def rotate_credential(
        self, credential_id: str, credential_values: dict, acting_user: str
    ) -> Dict:
        """Update stored credential values and push to all bound LiteLLM models.

        Returns a summary of how many models were synced.
        """
        if not self._credential_store:
            raise RuntimeError("Credential store is not available")

        updated = await self._credential_store.update_credential(
            credential_id, credential_values, acting_user
        )
        if not updated:
            raise ValueError(f"Credential '{credential_id}' not found")

        synced, failed = await self._sync_credential_to_models(credential_id, credential_values)
        return {"credential_id": credential_id, "models_synced": synced, "models_failed": failed}

    async def _sync_credential_to_models(
        self, credential_id: str, credential_values: dict
    ) -> tuple:
        """Push fresh credential values to every LiteLLM model bound to this credential.

        Uses LiteLLM's model update endpoint. Returns (synced_count, failed_count).
        """
        if not self._credential_store:
            return 0, 0

        bindings = await self._credential_store.get_models_for_credential(credential_id)
        synced, failed = 0, 0
        for binding in bindings:
            model_id = binding.get("litellm_model_id", "")
            if not model_id:
                continue
            try:
                await self._client_or_raise().update_model(
                    model_id, {"litellm_params": credential_values}
                )
                synced += 1
            except Exception as exc:
                logger.warning("Failed to sync credential to model %s: %s", model_id, exc)
                failed += 1
        return synced, failed

    # ------------------------------------------------------------------
    # Virtual keys
    # ------------------------------------------------------------------

    async def list_keys(self) -> List[Dict]:
        """Return LiteLLM keys enriched with Qubiva owner binding data."""
        keys = await self._client_or_raise().list_keys()
        if not self._key_binding_store:
            return keys
        bindings = await self._key_binding_store.list_bindings()
        bindings_by_key = {b["litellm_key"]: b for b in bindings}
        for key in keys:
            key_value = key.get("token") or key.get("key") or ""
            binding = bindings_by_key.get(key_value)
            if binding:
                key["key_type"] = binding["key_type"]
                key["project_name"] = binding.get("project_name")
                key["owner_username"] = binding.get("owner_username")
                key["created_by"] = binding.get("created_by")
            else:
                key["key_type"] = None
                key["project_name"] = None
                key["owner_username"] = None
                key["created_by"] = None
        return keys

    async def create_key(
        self,
        params: Dict,
        key_type: Optional[str] = None,
        project_name: Optional[str] = None,
        owner_username: Optional[str] = None,
        created_by: str = "",
    ) -> Dict:
        """Create a LiteLLM virtual key and bind it to a project or user.

        key_type: "project" — key scoped to a project (team_id = project_name)
                  "user"    — key scoped to a specific user (user_id = username)
        """
        cfg = self._get_config()
        defaults = cfg.get("defaults", {})
        if "max_budget" not in params and defaults.get("monthly_budget_usd") is not None:
            params.setdefault("max_budget", defaults["monthly_budget_usd"])
        if "rpm_limit" not in params and defaults.get("rpm_limit") is not None:
            params.setdefault("rpm_limit", defaults["rpm_limit"])
        if "tpm_limit" not in params and defaults.get("tpm_limit") is not None:
            params.setdefault("tpm_limit", defaults["tpm_limit"])

        # Set LiteLLM scoping params based on key type
        if key_type == "project" and project_name:
            params["team_id"] = project_name
        elif key_type == "user" and owner_username:
            params["user_id"] = owner_username

        result = await self._client_or_raise().create_key(params)

        # Bind the key to its Qubiva owner
        if self._key_binding_store and key_type:
            key_value = result.get("key") or result.get("token") or ""
            if key_value:
                try:
                    await self._key_binding_store.bind_key(
                        litellm_key=key_value,
                        key_type=key_type,
                        project_name=project_name if key_type == "project" else None,
                        owner_username=owner_username if key_type == "user" else None,
                        alias=params.get("alias"),
                        created_by=created_by,
                    )
                except Exception as exc:
                    logger.warning("Failed to store key binding: %s", exc)

        return result

    async def update_key(self, key: str, params: Dict) -> Dict:
        return await self._client_or_raise().update_key(key, params)

    async def delete_key(self, key: str) -> Dict:
        result = await self._client_or_raise().delete_key(key)
        if self._key_binding_store:
            try:
                await self._key_binding_store.delete_binding(key)
            except Exception as exc:
                logger.warning("Failed to remove key binding on delete: %s", exc)
        return result

    async def get_key_binding(self, litellm_key: str) -> Optional[Dict]:
        if not self._key_binding_store:
            return None
        return await self._key_binding_store.get_binding(litellm_key)

    # ------------------------------------------------------------------
    # Project tokens
    # ------------------------------------------------------------------

    async def create_project_token(
        self,
        project_name: str,
        token_name: str,
        roles: List[str],
        expiry_hours: int,
        created_by: str,
    ) -> Dict:
        if not self._project_token_store:
            raise RuntimeError("Project token store is not available")
        return await self._project_token_store.create_token(
            project_name=project_name,
            token_name=token_name,
            roles=roles,
            expiry_hours=expiry_hours,
            created_by=created_by,
        )

    async def list_project_tokens(self, project_name: str) -> List[Dict]:
        if not self._project_token_store:
            raise RuntimeError("Project token store is not available")
        return await self._project_token_store.list_tokens(project_name)

    async def revoke_project_token(self, project_name: str, token_id: str) -> bool:
        if not self._project_token_store:
            raise RuntimeError("Project token store is not available")
        return await self._project_token_store.revoke_token(project_name, token_id)

    async def validate_project_token_id(
        self, token_id: str, project_name: str
    ) -> Optional[Dict]:
        """Confirm a project token is active (used by the validate-token endpoint)."""
        if not self._project_token_store:
            return None
        return await self._project_token_store.validate_token_id(token_id, project_name)

    # ------------------------------------------------------------------
    # Spend / usage
    # ------------------------------------------------------------------

    async def get_spend_summary(self) -> Dict:
        client = self._client_or_raise()
        global_spend = await client.get_global_spend()
        by_key = await client.get_spend_by_key()
        by_model = await client.get_spend_by_model()
        return {
            "global": global_spend,
            "by_key": by_key,
            "by_model": by_model,
        }

    async def get_spend_logs(
        self, limit: int = 100, offset: int = 0,
        start_date: str = None, end_date: str = None
    ) -> List[Dict]:
        return await self._client_or_raise().get_spend_logs(
            limit=limit, offset=offset, start_date=start_date, end_date=end_date
        )
