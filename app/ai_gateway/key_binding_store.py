"""
Virtual key → Qubiva owner binding store.

Tracks which Qubiva entity (project or user) owns each LiteLLM virtual key,
enabling access control validation in the auth hook and key-owner display in the UI.
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("uvicorn.error")

KEY_BINDINGS_COLLECTION = "ai_gateway_key_bindings"


class KeyBindingStore:
    """Maps LiteLLM virtual keys to their Qubiva project or user owner."""

    def __init__(self, db_manager):
        self._db = db_manager

    async def bind_key(
        self,
        litellm_key: str,
        key_type: str,           # "project" | "user"
        project_name: Optional[str],
        owner_username: Optional[str],
        alias: Optional[str],
        created_by: str,
    ) -> None:
        doc = {
            "litellm_key": litellm_key,
            "key_type": key_type,
            "project_name": project_name,
            "owner_username": owner_username,
            "alias": alias,
            "created_by": created_by,
            "created_at": datetime.utcnow(),
        }
        await self._db.insert_document(KEY_BINDINGS_COLLECTION, doc)

    async def get_binding(self, litellm_key: str) -> Optional[Dict]:
        return await self._db.find_document(
            KEY_BINDINGS_COLLECTION, {"litellm_key": litellm_key}
        )

    async def list_bindings(self) -> List[Dict]:
        docs = await self._db.find_documents(KEY_BINDINGS_COLLECTION, {})
        return [
            {
                "litellm_key": d["litellm_key"],
                "key_type": d["key_type"],
                "project_name": d.get("project_name"),
                "owner_username": d.get("owner_username"),
                "alias": d.get("alias"),
                "created_by": d.get("created_by"),
                "created_at": d.get("created_at"),
            }
            for d in docs
        ]

    async def delete_binding(self, litellm_key: str) -> bool:
        count = await self._db.delete_document(
            KEY_BINDINGS_COLLECTION, {"litellm_key": litellm_key}
        )
        return count > 0

    async def count_bindings_for_project(self, project_name: str) -> int:
        docs = await self._db.find_documents(
            KEY_BINDINGS_COLLECTION, {"key_type": "project", "project_name": project_name}
        )
        return len(docs)

    async def count_bindings_for_user(self, username: str) -> int:
        docs = await self._db.find_documents(
            KEY_BINDINGS_COLLECTION, {"key_type": "user", "owner_username": username}
        )
        return len(docs)
