"""
Plan artifact storage for Terraform plan/apply split.

Stores plan binary files (tfplan.bin) on the local filesystem PVC so the
apply runner pod can download and use them without re-running plan.
"""

import base64
import logging
import os

logger = logging.getLogger("uvicorn.error")

_PLANS_PREFIX = "plans"


class PlanStore:
    """Filesystem-backed store for Terraform plan binaries and output text."""

    def __init__(self):
        self.base_dir = os.getenv("ARTIFACTS_STORAGE_PATH", "/app/data/artifacts")
        self._plans_dir = os.path.join(self.base_dir, _PLANS_PREFIX)
        os.makedirs(self._plans_dir, exist_ok=True)

    def _plan_dir(self, request_id: str) -> str:
        return os.path.join(self._plans_dir, request_id)

    def _binary_path(self, request_id: str) -> str:
        return os.path.join(self._plan_dir(request_id), "tfplan.bin")

    def save_plan_binary(self, request_id: str, binary_b64: str) -> None:
        """Decode a base64-encoded plan binary and write it to the filesystem."""
        plan_dir = self._plan_dir(request_id)
        os.makedirs(plan_dir, exist_ok=True)
        binary = base64.b64decode(binary_b64)
        with open(self._binary_path(request_id), "wb") as f:
            f.write(binary)
        logger.info("Plan binary saved for request %s (%d bytes)", request_id, len(binary))

    def get_plan_binary(self, request_id: str) -> bytes:
        """Return the raw plan binary bytes, or raise FileNotFoundError."""
        path = self._binary_path(request_id)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"No plan binary found for request {request_id}")
        with open(path, "rb") as f:
            return f.read()

    def has_plan_binary(self, request_id: str) -> bool:
        return os.path.isfile(self._binary_path(request_id))

    def delete_plan(self, request_id: str) -> None:
        """Remove stored plan artifacts after apply completes or is rejected."""
        import shutil
        plan_dir = self._plan_dir(request_id)
        if os.path.isdir(plan_dir):
            shutil.rmtree(plan_dir, ignore_errors=True)
            logger.debug("Plan artifacts deleted for request %s", request_id)
