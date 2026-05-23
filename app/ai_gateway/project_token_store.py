"""
Project token storage.

Project tokens are identity-less JWTs scoped to a project.
They carry project roles (same role set as project members) and cannot be used
to log into the Qubiva web UI.  Created by project admins (or org admins) and
assigned roles at creation time, just like a project member.

The raw JWT is returned once on creation and never stored — only metadata is persisted.
Validation uses the token_id claim inside the JWT to confirm the token is still active.
"""
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("uvicorn.error")

PROJECT_TOKENS_COLLECTION = "ai_gateway_project_tokens"


class ProjectTokenStore:
    """Create, list, and revoke project-scoped identity tokens."""

    def __init__(self, db_manager, kms_manager):
        self._db = db_manager
        self._kms = kms_manager

    def _generate_token(
        self,
        token_id: str,
        project_name: str,
        roles: List[str],
        expiry_hours: int,
    ) -> str:
        return self._kms.create_jwt(
            subject=f"project:{project_name}",
            expiry_hours=expiry_hours,
            additional_claims={
                "token_type": "project_token",
                "token_id": token_id,
                "project_name": project_name,
                "roles": roles,
            },
        )

    async def create_token(
        self,
        project_name: str,
        token_name: str,
        roles: List[str],
        expiry_hours: int,
        created_by: str,
    ) -> Dict:
        """
        Generate a project token JWT and persist its metadata.

        Returns a dict containing the raw token value (shown once, never stored).
        """
        # Reject duplicate token names within the same project
        existing = await self._db.find_documents(
            PROJECT_TOKENS_COLLECTION,
            {"project_name": project_name, "token_name": token_name, "active": True},
        )
        if existing:
            raise ValueError(f"Token name '{token_name}' already exists in project '{project_name}'")

        token_id = str(uuid.uuid4())
        token_value = self._generate_token(token_id, project_name, roles, expiry_hours)

        doc = {
            "token_id": token_id,
            "token_name": token_name,
            "project_name": project_name,
            "roles": roles,
            "expiry_hours": expiry_hours,
            "created_by": created_by,
            "created_at": datetime.utcnow(),
            "active": True,
        }
        await self._db.insert_document(PROJECT_TOKENS_COLLECTION, doc)

        return {
            "token_id": token_id,
            "token_name": token_name,
            "project_name": project_name,
            "roles": roles,
            "token": token_value,  # returned once only
        }

    async def list_tokens(self, project_name: str) -> List[Dict]:
        """Return token metadata for a project (no token values)."""
        docs = await self._db.find_documents(
            PROJECT_TOKENS_COLLECTION,
            {"project_name": project_name, "active": True},
        )
        return [
            {
                "token_id": d["token_id"],
                "token_name": d["token_name"],
                "project_name": d["project_name"],
                "roles": d.get("roles", []),
                "expiry_hours": d.get("expiry_hours"),
                "created_by": d.get("created_by"),
                "created_at": d.get("created_at"),
            }
            for d in docs
        ]

    async def revoke_token(self, project_name: str, token_id: str) -> bool:
        """Mark a token as inactive. Returns True if found and revoked."""
        count = await self._db.update_document(
            PROJECT_TOKENS_COLLECTION,
            {"token_id": token_id, "project_name": project_name, "active": True},
            {"$set": {"active": False, "revoked_at": datetime.utcnow()}},
        )
        return count > 0

    async def validate_token_id(
        self, token_id: str, project_name: str
    ) -> Optional[Dict]:
        """
        Confirm a project token is still active.

        Called by the validate-token endpoint after JWT signature verification
        to check the token has not been revoked.
        Returns metadata dict or None if not found / revoked.
        """
        doc = await self._db.find_document(
            PROJECT_TOKENS_COLLECTION,
            {"token_id": token_id, "project_name": project_name, "active": True},
        )
        if not doc:
            return None
        return {
            "token_id": doc["token_id"],
            "project_name": doc["project_name"],
            "roles": doc.get("roles", []),
        }
