import asyncio
import logging
import os
from typing import Optional
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from kubernetes_asyncio import client as k8s_client, config as k8s_config

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class CloudWatchLogStreamer:
    """
    Log streamer using Kubernetes pod logs instead of CloudWatch.
    Keeps the same class name for backward compatibility.
    """

    def __init__(self, db_manager, log_persistence=None):
        self.db_manager = db_manager
        self.log_persistence = log_persistence
        self.max_retries = 12
        self.retry_delay = 5
        self.namespace = os.getenv('K8S_NAMESPACE', 'default')
        self._k8s_initialized = False
        self._k8s_cfg = None  # fixed Configuration for in-cluster auth workaround

    async def _query_persisted_logs(self, request_id: str) -> Optional[str]:
        """Fetch historical logs from Loki, falling back to MongoDB partial_logs field.

        partial_logs is always written by the stop endpoint (and iac_executor
        _persist_logs) so logs are readable instantly on page refresh, even
        when Loki is available but has an indexing delay.
        """
        # Try Loki first
        if self.log_persistence:
            try:
                loki_text = await self.log_persistence.query_logs(request_id)
                if loki_text:
                    return loki_text
            except Exception as e:
                logger.warning(f"Failed to query persisted logs for {request_id}: {e}")

        # Fallback: partial_logs stored directly in the request document
        try:
            doc = await self.db_manager.find_document("requests", {"request_id": request_id})
            if doc and doc.get("partial_logs"):
                return doc["partial_logs"]
        except Exception as e:
            logger.warning(f"Failed to query partial_logs from MongoDB for {request_id}: {e}")

        return None

    async def _stream_persisted_logs(self, websocket: WebSocket, request_id: str) -> bool:
        """Stream historical logs from Loki if available."""
        try:
            log_text = await self._query_persisted_logs(request_id)
            if not log_text:
                return False

            await self.send_info_message(websocket, "Streaming persisted logs from storage...")
            for line in log_text.split('\n'):
                if not line:
                    continue
                # Handle bytes-repr strings stored by older code (e.g. b'...\n...')
                # These are entire log blobs stored as str(bytes) with escaped newlines.
                if line.startswith("b'") or line.startswith('b"'):
                    try:
                        import ast
                        raw = ast.literal_eval(line)
                        if isinstance(raw, bytes):
                            for real_line in raw.decode('utf-8', errors='replace').split('\n'):
                                if real_line:
                                    await websocket.send_text(real_line)
                            continue
                    except Exception:
                        pass
                await websocket.send_text(line)
            return True
        except Exception as e:
            logger.warning(f"Failed to stream persisted logs for {request_id}: {e}")
            return False

    async def get_full_logs(self, request_id: str) -> Optional[str]:
        """Return full logs for a request from pod (if alive) or persisted storage."""
        try:
            await self._ensure_k8s_client()
        except Exception:
            return await self._query_persisted_logs(request_id)

        pod_name, container_name = await self.get_log_stream_details(request_id)
        if pod_name:
            _api = k8s_client.ApiClient(configuration=self._k8s_cfg) if self._k8s_cfg else k8s_client.ApiClient()
            v1 = k8s_client.CoreV1Api(api_client=_api)
            try:
                kwargs = {
                    'name': pod_name,
                    'namespace': self.namespace,
                    'follow': False,
                    'tail_lines': 50000,
                }
                if container_name:
                    kwargs['container'] = container_name

                log_text = await v1.read_namespaced_pod_log(**kwargs)
                if log_text:
                    return log_text
            except Exception:
                # Pod may be gone; fall back to persisted logs.
                pass
            finally:
                try:
                    await v1.api_client.close()
                except Exception:
                    pass

        return await self._query_persisted_logs(request_id)

    async def _ensure_k8s_client(self):
        """Lazy-initialize K8s client"""
        if not self._k8s_initialized:
            try:
                try:
                    k8s_config.load_incluster_config()
                except k8s_config.ConfigException:
                    await k8s_config.load_kube_config()
                # kubernetes-python-client v29+ bug: auth_settings() checks
                # api_key['BearerToken'] but load_incluster_config() writes
                # api_key['authorization'], so no auth header is sent (system:anonymous).
                # Fix: wrap the refresh hook to keep both keys in sync.
                cfg = k8s_client.Configuration.get_default_copy()
                if 'authorization' in cfg.api_key and 'BearerToken' not in cfg.api_key:
                    orig_hook = cfg.refresh_api_key_hook

                    def _make_hook(h):
                        def _hook(c):
                            if h:
                                h(c)
                            if 'authorization' in c.api_key:
                                c.api_key['BearerToken'] = c.api_key['authorization']
                        return _hook
                    cfg.refresh_api_key_hook = _make_hook(orig_hook)
                    cfg.refresh_api_key_hook(cfg)
                self._k8s_cfg = cfg
                self._k8s_initialized = True
            except k8s_config.ConfigException:
                logger.warning("No Kubernetes config found — live log streaming disabled")
                self._k8s_initialized = False

    async def get_log_stream_details(self, request_id):
        """Get pod name and container name from request document"""
        document = await self.db_manager.find_document("requests", {"request_id": request_id})
        if document and "logs" in document and document["logs"]:
            # Format: "pod_name:container_name" or just "pod_name"
            parts = document["logs"].split(":")
            pod_name = parts[0]
            container_name = parts[1] if len(parts) > 1 else None
            return pod_name, container_name
        return None, None

    async def send_info_message(self, websocket: WebSocket, message: str):
        await websocket.send_text(f"Qubiva: > {message}")

    async def stream_logs(self, websocket: WebSocket, request_id: str):
        try:
            await self._ensure_k8s_client()

            # Two-phase run (plan → approval → apply): replay plan-phase logs first
            doc = await self.db_manager.find_document("requests", {"request_id": request_id})
            if doc and doc.get("plan_logs"):
                await self.send_info_message(websocket, "--- Plan phase logs ---")
                await self._stream_persisted_logs(websocket, request_id)
                await self.send_info_message(websocket, "--- Apply phase logs ---")

            # If the run is queued, wait for it to leave that state before
            # attempting pod log streaming — no point retrying for a pod that
            # hasn't been scheduled yet.
            while True:
                current_doc = await self.db_manager.find_document("requests", {"request_id": request_id})
                current_state = (current_doc or {}).get("state", "")
                if current_state != "queued":
                    break
                await self.send_info_message(websocket, "Run is queued — waiting for workspace to become available...")
                await asyncio.sleep(5)

            # If already in a terminal state, show any persisted logs then exit.
            # This path is hit both when a queued run is cancelled before starting
            # AND when the page is refreshed for an already-finished run.
            # We try Loki first then fall back to the MongoDB partial_logs field
            # so logs are visible even in environments without a Loki instance.
            current_doc = await self.db_manager.find_document("requests", {"request_id": request_id})
            current_state = (current_doc or {}).get("state", "")
            if current_state in ("cancelled", "rejected", "failed", "approval_timed_out"):
                await self._stream_persisted_logs(websocket, request_id)
                await self.send_info_message(websocket, f"Run {current_state}.")
                await websocket.close(code=1000)
                return

            pod_name, container_name = None, None
            for attempt in range(self.max_retries):
                pod_name, container_name = await self.get_log_stream_details(request_id)
                if pod_name:
                    await self.send_info_message(websocket, f"Connected to pod logs: {pod_name}")
                    break

                if attempt < self.max_retries - 1:
                    await self.send_info_message(websocket, f"Logs are not ready. Retrying in {self.retry_delay} seconds... (Attempt {attempt + 1}/{self.max_retries})")
                    await asyncio.sleep(self.retry_delay)
                else:
                    streamed = await self._stream_persisted_logs(websocket, request_id)
                    if streamed:
                        await self.send_info_message(websocket, "Log streaming completed.")
                        await websocket.close(code=1000)
                        return

                    await self.send_info_message(websocket, "Logs are not available after multiple retries. Please refresh the page or try again later.")
                    return

            # Stream logs from Kubernetes pod
            _api = k8s_client.ApiClient(configuration=self._k8s_cfg) if self._k8s_cfg else k8s_client.ApiClient()
            v1 = k8s_client.CoreV1Api(api_client=_api)
            try:
                kwargs = {
                    'name': pod_name,
                    'namespace': self.namespace,
                    'follow': True,
                    '_preload_content': False,
                }
                if container_name:
                    kwargs['container'] = container_name

                resp = await v1.read_namespaced_pod_log(**kwargs)

                # Check HTTP status — with _preload_content=False, a 404
                # returns the error JSON as stream content instead of raising.
                resp_status = getattr(resp, 'status', 200)
                if resp_status >= 400:
                    raise k8s_client.ApiException(status=resp_status, reason="Pod not found")

                async for line in resp.content:
                    if isinstance(line, bytes):
                        line = line.decode('utf-8')
                    line = line.rstrip('\n')
                    if line:
                        # Safety net: detect K8s error JSON that slipped through
                        if line.startswith('{"kind":"Status"') and '"NotFound"' in line:
                            raise k8s_client.ApiException(status=404, reason="Pod not found")
                        await websocket.send_text(line)

            except Exception as e:
                error_str = str(e)
                if 'not found' in error_str.lower() or '404' in error_str:
                    # Pod has been cleaned up — try persisted logs from Loki
                    streamed = await self._stream_persisted_logs(websocket, request_id)
                    if not streamed:
                        await self.send_info_message(websocket, "Pod has been cleaned up and no persisted logs found in Loki.")
                elif 'waiting to start' in error_str.lower() or 'is not ready' in error_str.lower():
                    await self.send_info_message(websocket, f"Container is starting up. Details: {error_str}")
                else:
                    await self.send_info_message(websocket, f"Error streaming logs: {error_str}")

            await self.send_info_message(websocket, "Log streaming completed.")
            await websocket.close(code=1000)
            await v1.api_client.close()
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected while streaming logs for request {request_id}")
        except Exception as e:
            logger.error(f"Error in log streamer: {str(e)}")
            try:
                await self.send_info_message(websocket, f"Log streaming error: {str(e)}")
            except Exception:
                pass
