"""
Request management routes for Qubiva.

Request details, stop, artifacts, logs, and WebSocket endpoints.
"""

import os
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect

from app.deps import (
    artifacts_handler,
    logstreamer,
    get_request_tracker,
    get_log_streamer,
)
from app.auth_helpers import authenticate_http_user, authenticate_websocket_user
from app.decorators import permissions
from app.request_manager import RequestTracker
from app.log_streamer import CloudWatchLogStreamer
from app.artifacts_downloader import (
    RequestIDNotFoundError,
    NoFilesFoundError,
    ArtifactsHandlerError,
)
from fastapi.responses import FileResponse

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.websocket("/api/v1/projects/{project_name}/requests/get_status_updates/{request_type}")
@permissions(["project_workspace_execute"])
async def request_updates(
    websocket: WebSocket,
    request_type: str,
    user: dict = Depends(authenticate_websocket_user),
    user_permissions: List[str] = Depends(lambda: []),
    tracker: RequestTracker = Depends(get_request_tracker),
):
    await websocket.accept()
    await tracker.register_websocket(websocket, request_type)

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "update_tracked":
                request_ids = data.get("request_ids", [])
                await tracker.update_tracked_requests(
                    websocket, request_type, request_ids
                )
            elif data.get("type") == "heartbeat":
                await websocket.send_json({"type": "heartbeat_ack"})
    except WebSocketDisconnect:
        await tracker.unregister_websocket(websocket, request_type)
    except Exception as e:
        print(f"WebSocket error: {str(e)}")
        await tracker.unregister_websocket(websocket, request_type)


@router.websocket("/api/v1/projects/{project_name}/requests/stream_logs/{request_id}")
@permissions(["project_workspace_execute"])
async def websocket_endpoint(
    websocket: WebSocket,
    request_id: str,
    user: dict = Depends(authenticate_websocket_user),
    user_permissions: List[str] = Depends(lambda: []),
    streamer: CloudWatchLogStreamer = Depends(get_log_streamer),
):
    await websocket.accept()
    await streamer.stream_logs(websocket, request_id)


@router.get("/api/v1/projects/{project_name}/requests/{request_id}")
@permissions(["project_workspace_execute"])
async def get_request_details(
    request_id: str,
    tracker: RequestTracker = Depends(get_request_tracker),
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, result = await tracker.get_request_details(request_id)

    if not success:
        raise HTTPException(status_code=500, detail=str(result))

    return result


@router.post("/api/v1/projects/{project_name}/requests/{request_id}/stop")
@permissions(["project_workspace_execute"])
async def stop_request_execution(
    project_name: str,
    request_id: str,
    tracker: RequestTracker = Depends(get_request_tracker),
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Stop a running execution by deleting its K8s Job."""
    from kubernetes import client as k8s_client, config as k8s_config

    success, request_details = await tracker.get_request_details(request_id)
    if not success:
        raise HTTPException(status_code=404, detail="Request not found")

    current_state = request_details.get("state", "")
    terminal_states = RequestTracker.TERMINAL_STATES
    if current_state in terminal_states:
        raise HTTPException(status_code=400, detail=f"Request already in terminal state: {current_state}")

    job_name = request_details.get("job_name")
    if not job_name:
        raise HTTPException(status_code=400, detail="No K8s job associated with this request")

    # Delete the K8s Job
    try:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        # kubernetes-python-client v29+ bug: auth_settings() checks
        # api_key['BearerToken'] but load_incluster_config() writes
        # api_key['authorization'], so no auth header is sent (system:anonymous).
        # Fix: wrap the refresh hook to keep both keys in sync.
        _cfg = k8s_client.Configuration.get_default_copy()
        if 'authorization' in _cfg.api_key and 'BearerToken' not in _cfg.api_key:
            _orig = _cfg.refresh_api_key_hook

            def _make_hook(h):
                def _hook(c):
                    if h:
                        h(c)
                    if 'authorization' in c.api_key:
                        c.api_key['BearerToken'] = c.api_key['authorization']
                return _hook
            _cfg.refresh_api_key_hook = _make_hook(_orig)
            _cfg.refresh_api_key_hook(_cfg)
        batch_v1 = k8s_client.BatchV1Api(api_client=k8s_client.ApiClient(configuration=_cfg))
        namespace = os.environ.get('K8S_NAMESPACE', 'default')
        batch_v1.delete_namespaced_job(
            name=job_name,
            namespace=namespace,
            body=k8s_client.V1DeleteOptions(propagation_policy='Foreground')
        )
        logger.info(f"Job {job_name} stopped by user {user.get('username')} for request {request_id}")
    except k8s_client.ApiException as e:
        if e.status != 404:
            logger.error(f"Failed to delete job {job_name}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to stop job: {e.reason}")
        # 404 = job already gone, that's fine

    # Update request state
    stopped_by = user.get("username", "unknown")
    await tracker.update_error_details(request_id, f"Stopped by {stopped_by}")
    await tracker.update_request_state(request_id, "cancelled")

    return {"status": "success", "message": f"Execution stopped for request {request_id}"}


@router.get("/api/v1/projects/{project_name}/requests/{request_id}/artifacts/check")
@permissions(["project_workspace_execute"])
async def check_artifacts(
    project_name: str,
    request_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    return {"available": artifacts_handler.has_artifacts(request_id)}


@router.get("/api/v1/projects/{project_name}/requests/{request_id}/artifacts")
@permissions(["project_workspace_execute"])
async def download_artifacts(
    project_name: str,
    request_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    try:
        file_path = artifacts_handler.get_download_url(request_id)
        filename = os.path.basename(file_path)
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/zip"
        )
    except RequestIDNotFoundError:
        raise HTTPException(status_code=404, detail="Request ID not found")
    except NoFilesFoundError:
        raise HTTPException(status_code=404, detail="No files found for this request")
    except ArtifactsHandlerError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/projects/{project_name}/requests/{request_id}/logs/download")
@permissions(["project_workspace_execute"])
async def download_logs(
    project_name: str,
    request_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    try:
        log_text = await logstreamer.get_full_logs(request_id)
        if not log_text:
            raise HTTPException(status_code=404, detail="No logs found for this request")

        return Response(
            content=log_text,
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{request_id}.log"'
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download logs: {e}")
