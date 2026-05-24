"""
LiteLLM proxy REST API client.

Thin async HTTP wrapper around LiteLLM's management endpoints.
All governance logic lives in AIGatewayManager; this layer only handles
network transport and deserialization.
"""
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("uvicorn.error")


class AIGatewayClient:
    """Async HTTP client for LiteLLM proxy management API."""

    def __init__(self, base_url: str, master_key: str, timeout: int = 30):
        self._base_url = base_url.rstrip("/")
        self._master_key = master_key
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._master_key}"},
                timeout=self._timeout,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        resp = await self._get_client().get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: Dict) -> Any:
        resp = await self._get_client().post(path, json=body)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str, body: Optional[Dict] = None) -> Any:
        resp = await self._get_client().request("DELETE", path, json=body)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    async def list_models(self) -> List[Dict]:
        """Return all models configured in LiteLLM."""
        try:
            data = await self._get("/model/info")
            return data.get("data", [])
        except httpx.HTTPStatusError as exc:
            # LiteLLM returns 500 when no models are configured yet
            if exc.response.status_code == 500:
                return []
            raise

    async def add_model(self, model_params: Dict) -> Dict:
        """Add a new model to LiteLLM. model_params follows LiteLLM schema."""
        return await self._post("/model/new", model_params)

    async def delete_model(self, model_id: str) -> Dict:
        """Delete a model by its LiteLLM model_id."""
        return await self._post("/model/delete", {"id": model_id})

    async def update_model(self, model_id: str, params: Dict) -> Dict:
        """Update a model's parameters (e.g. rotate api_key in-place)."""
        body = {"model_id": model_id, **params}
        return await self._post("/model/update", body)

    # ------------------------------------------------------------------
    # Virtual keys
    # ------------------------------------------------------------------

    async def list_keys(self) -> List[Dict]:
        """Return all virtual keys with full details."""
        data = await self._get("/key/list")
        hashes = data.get("keys", [])
        results = []
        for h in hashes:
            if not isinstance(h, str):
                results.append(h)
                continue
            try:
                info_data = await self._get("/key/info", params={"key": h})
                info = info_data.get("info", {})
                info["token"] = h
                results.append(info)
            except Exception:
                results.append({"token": h})
        return results

    async def create_key(self, params: Dict) -> Dict:
        """Create a virtual key. params may include budget, rate limits, metadata."""
        return await self._post("/key/generate", params)

    async def update_key(self, key: str, params: Dict) -> Dict:
        """Update a virtual key's budget/limits."""
        body = {"key": key, **params}
        return await self._post("/key/update", body)

    async def delete_key(self, key: str) -> Dict:
        """Delete a virtual key."""
        return await self._delete("/key/delete", {"keys": [key]})

    # ------------------------------------------------------------------
    # Spend / usage
    # ------------------------------------------------------------------

    async def get_global_spend(self) -> Dict:
        """Return global spend summary."""
        return await self._get("/global/spend")

    async def get_spend_by_key(self) -> List[Dict]:
        """Return spend broken down per virtual key."""
        data = await self._get("/spend/keys")
        return data if isinstance(data, list) else data.get("data", [])

    async def get_spend_by_model(self) -> List[Dict]:
        """Return spend broken down per model."""
        data = await self._get("/global/spend/models")
        return data if isinstance(data, list) else data.get("data", [])

    async def get_spend_logs(
        self, limit: int = 100, offset: int = 0,
        start_date: str = None, end_date: str = None
    ) -> List[Dict]:
        """Return detailed spend/call logs."""
        from datetime import date, timedelta
        params: Dict = {"limit": limit, "offset": offset}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            # LiteLLM end_date is exclusive — add 1 day so the chosen date is included
            try:
                params["end_date"] = (date.fromisoformat(end_date) + timedelta(days=1)).isoformat()
            except ValueError:
                params["end_date"] = end_date
        data = await self._get("/spend/logs", params=params)
        return data if isinstance(data, list) else data.get("data", [])

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Return True if the gateway is reachable and ready."""
        try:
            await self._get("/health/readiness")
            return True
        except Exception:
            return False
