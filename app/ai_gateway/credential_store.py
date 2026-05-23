"""
LLM provider credential storage.

Stores LLM provider API keys (OpenAI, Anthropic, Groq, etc.) encrypted
in MongoDB via KMS, separate from cloud infrastructure credentials.

Tracks which LiteLLM model IDs use which credential, enabling automatic
credential rotation sync: when a key is updated here, push the new key
to every LiteLLM model that references it.
"""
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("uvicorn.error")

CREDENTIALS_COLLECTION = "ai_gateway_credentials"
BINDINGS_COLLECTION = "ai_gateway_model_bindings"


class LLMCredentialStore:
    """Encrypted storage for LLM provider API keys with model binding tracking."""

    def __init__(self, db_manager, kms_manager):
        self._db = db_manager
        self._kms = kms_manager

    def _encrypt(self, value: str) -> str:
        return self._kms.encrypt(value)

    def _decrypt(self, value: str) -> str:
        return self._kms.decrypt(encrypted_data=value)

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    async def store_credential(
        self, name: str, provider: str, credential_values: dict, acting_user: str
    ) -> str:
        """Encrypt and store credential values. Returns the credential_id."""
        credential_id = str(uuid.uuid4())
        doc = {
            "credential_id": credential_id,
            "name": name,
            "provider": provider,
            "credential_values_enc": self._encrypt(json.dumps(credential_values)),
            "created_by": acting_user,
            "created_at": datetime.utcnow(),
        }
        await self._db.insert_document(CREDENTIALS_COLLECTION, doc)
        return credential_id

    async def list_credentials(self) -> List[Dict]:
        """Return all credentials without exposing API keys."""
        docs = await self._db.find_documents(CREDENTIALS_COLLECTION, {})
        return [
            {
                "credential_id": d["credential_id"],
                "name": d["name"],
                "provider": d["provider"],
                "created_by": d.get("created_by"),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
            }
            for d in docs
        ]

    async def get_credential_values(self, credential_id: str) -> Optional[dict]:
        """Decrypt and return the credential values dict for internal use only."""
        doc = await self._db.find_document(
            CREDENTIALS_COLLECTION, {"credential_id": credential_id}
        )
        if not doc:
            return None
        return json.loads(self._decrypt(doc["credential_values_enc"]))

    async def get_credential_meta(self, credential_id: str) -> Optional[Dict]:
        """Return credential metadata (no key) for a single credential."""
        doc = await self._db.find_document(
            CREDENTIALS_COLLECTION, {"credential_id": credential_id}
        )
        if not doc:
            return None
        return {
            "credential_id": doc["credential_id"],
            "name": doc["name"],
            "provider": doc["provider"],
            "created_by": doc.get("created_by"),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
        }

    async def update_credential(
        self, credential_id: str, credential_values: dict, acting_user: str
    ) -> bool:
        """Rotate credential values. Returns True if found and updated."""
        count = await self._db.update_document(
            CREDENTIALS_COLLECTION,
            {"credential_id": credential_id},
            {
                "$set": {
                    "credential_values_enc": self._encrypt(json.dumps(credential_values)),
                    "updated_by": acting_user,
                    "updated_at": datetime.utcnow(),
                }
            },
        )
        return count > 0

    async def delete_credential(self, credential_id: str) -> bool:
        count = await self._db.delete_document(
            CREDENTIALS_COLLECTION, {"credential_id": credential_id}
        )
        return count > 0

    # ------------------------------------------------------------------
    # Model-credential bindings
    # ------------------------------------------------------------------

    async def bind_model(
        self,
        litellm_model_id: str,
        model_name: str,
        credential_id: str,
        litellm_params: Dict,
        credential_keys: List[str],
        model_info: Optional[Dict] = None,
    ):
        """Record that a LiteLLM model uses a specific credential.

        Stores the litellm_params (without credential fields) so the model can be
        re-created with fresh values during rotation.
        """
        params_without_key = {k: v for k, v in litellm_params.items() if k not in credential_keys}
        await self._db.update_one_document(
            BINDINGS_COLLECTION,
            {"litellm_model_id": litellm_model_id},
            {
                "$set": {
                    "model_name": model_name,
                    "credential_id": credential_id,
                    "litellm_params": params_without_key,
                    "model_info": model_info,
                }
            },
            upsert=True,
        )

    async def get_binding(self, litellm_model_id: str) -> Optional[Dict]:
        return await self._db.find_document(
            BINDINGS_COLLECTION, {"litellm_model_id": litellm_model_id}
        )

    async def get_models_for_credential(self, credential_id: str) -> List[Dict]:
        """Return all model bindings that use a given credential."""
        return await self._db.find_documents(
            BINDINGS_COLLECTION, {"credential_id": credential_id}
        )

    async def unbind_model(self, litellm_model_id: str):
        """Remove a model-credential binding when a model is deleted."""
        await self._db.delete_document(
            BINDINGS_COLLECTION, {"litellm_model_id": litellm_model_id}
        )
