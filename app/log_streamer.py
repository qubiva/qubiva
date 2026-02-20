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

    async def _query_persisted_logs(self, request_id: str) -> Optional[str]:
        """Fetch historical logs from Loki if available."""
        if not self.log_persistence:
            return None
        try:
            return await self.log_persistence.query_logs(request_id)
        except Exception as e:
            logger.warning(f"Failed to query persisted logs for {request_id}: {e}")
            return None

    async def _stream_persisted_logs(self, websocket: WebSocket, request_id: str) -> bool:
        """Stream historical logs from Loki if available."""
        try:
            log_text = await self._query_persisted_logs(request_id)
            if not log_text:
                return False

            await self.send_info_message(websocket, "Streaming persisted logs from storage...")
            for line in log_text.split('\n'):
                if line:
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
            v1 = k8s_client.CoreV1Api()
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
            v1 = k8s_client.CoreV1Api()
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
