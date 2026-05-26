"""
Request management routes for Qubiva.

Request details, stop, artifacts, logs, and WebSocket endpoints.
"""

import asyncio
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
    """Stop a running execution gracefully.

    1. Finds the runner pod (pool pod via 'logs' field, or job pod via job label).
    2. Creates /tmp/cancel_requested in the pod — the runner's cancel watcher sends
       SIGTERM to terraform/tofu, giving it time to save state before exiting.
    3. Waits up to 30 s for the pod to terminate.
    4. Captures partial pod logs and persists them to Loki so the log viewer can
       replay them after the run is marked cancelled.
    5. Deletes the K8s Job (job-mode only; pool-mode cleanup is handled by
       monitor_execution's finally block when it sees the terminal state).
    """
    from kubernetes import client as k8s_client, config as k8s_config
    from app.deps import log_persistence

    success, request_details = await tracker.get_request_details(request_id)
    if not success:
        raise HTTPException(status_code=404, detail="Request not found")

    current_state = request_details.get("state", "")
    if current_state in RequestTracker.TERMINAL_STATES:
        raise HTTPException(status_code=400, detail=f"Request already in terminal state: {current_state}")

    job_name = request_details.get("job_name")

    # --- Kubernetes client setup (with in-cluster auth workaround) ---
    try:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config()
        _cfg = k8s_client.Configuration.get_default_copy()
        # kubernetes-python-client v29+ bug: auth_settings() checks api_key['BearerToken']
        # but load_incluster_config() writes api_key['authorization'].
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
        core_v1 = k8s_client.CoreV1Api(api_client=k8s_client.ApiClient(configuration=_cfg))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Kubernetes client error: {e}")

    namespace = os.environ.get('K8S_NAMESPACE', 'default')

    # --- Resolve pod name ---
    # Pool pods: pod name stored in request doc "logs" field as "pod_name[:container_name]"
    pod_name = None
    container_name = "iac-runner"
    logs_ref = request_details.get("logs", "")
    if logs_ref:
        parts = logs_ref.split(":")
        pod_name = parts[0]
        container_name = parts[1] if len(parts) > 1 else "iac-runner"

    # Job pods: find associated pod via the job-name label
    if not pod_name and job_name:
        try:
            pods = await asyncio.to_thread(
                core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"job-name={job_name}",
            )
            if pods.items:
                pod_name = pods.items[0].metadata.name
        except Exception as e:
            logger.warning(f"Could not list pods for job {job_name}: {e}")

    logger.info(f"[stop] request={request_id} pod_name={pod_name!r} job_name={job_name!r} logs_ref={logs_ref!r}")
    if not pod_name and not job_name:
        # Nothing to stop (run may not have a pod yet); fall through to state update
        logger.warning(f"No pod or job found for request {request_id} — updating state only")

    # --- Signal graceful cancel ---
    # Creates /tmp/cancel_requested inside the pod.  The runner's cancel watcher
    # (a background subshell in runner.sh) detects this file, sends SIGTERM to
    # terraform/tofu so it can save state cleanly, then exits.
    if pod_name:
        try:
            from kubernetes.stream import stream as k8s_stream

            def _exec_cancel():
                k8s_stream(
                    core_v1.connect_get_namespaced_pod_exec,
                    name=pod_name,
                    namespace=namespace,
                    container=container_name,
                    command=["/bin/sh", "-c",
                             "touch /tmp/cancel_requested; "
                             "kill -TERM 1; "
                             "pkill -TERM -P 1 2>/dev/null; "
                             "true"],
                    stderr=True, stdout=True, stdin=False, tty=False,
                )
            await asyncio.wait_for(asyncio.to_thread(_exec_cancel), timeout=10)
            logger.info(f"Sent cancel signal to pod {pod_name} for request {request_id}")
        except Exception as e:
            # Pod may have already exited or exec may be unavailable — not fatal
            logger.warning(f"Could not signal cancel to pod {pod_name}: {e}")

        # --- Wait for pod to terminate (up to 30 s) ---
        for _ in range(10):
            await asyncio.sleep(3)
            try:
                pod_status = await asyncio.to_thread(
                    core_v1.read_namespaced_pod_status,
                    name=pod_name,
                    namespace=namespace,
                )
                if pod_status.status.phase in ("Succeeded", "Failed"):
                    logger.info(f"Pod {pod_name} terminated after cancel signal")
                    break
            except k8s_client.ApiException as poll_err:
                if poll_err.status == 404:
                    logger.info(f"Pod {pod_name} already gone")
                    break
            except Exception:
                pass

        # --- Capture and persist partial logs ---
        # Must happen BEFORE job/pod deletion so logs survive.
        # Pool-mode monitor_execution also calls _persist_pod_logs in its finally
        # block; if the pod is gone by then, it skips silently — this capture wins.
        try:
            def _read_logs():
                return core_v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    container=container_name,
                    tail_lines=50000,
                )
            log_text = await asyncio.wait_for(asyncio.to_thread(_read_logs), timeout=15)
            logger.info(f"[stop] pod={pod_name} log_text len={len(log_text) if log_text else 'None/empty'!r}")
            if log_text:
                if isinstance(log_text, bytes):
                    log_text = log_text.decode("utf-8", errors="replace")

                # Push to Loki for long-term storage.
                pushed_to_loki = False
                if log_persistence:
                    pushed_to_loki = await log_persistence.push_logs(
                        request_id=request_id,
                        job_type="iac",
                        project_name=project_name,
                        log_text=log_text,
                    )

                # Always write to MongoDB partial_logs for immediate availability.
                # Loki has an indexing delay — query_range returns empty for
                # several seconds after a successful push, so the log viewer
                # would show nothing on an immediate page refresh.  MongoDB is
                # readable the instant the document is written.
                fallback_text = log_text[-512000:] if len(log_text) > 512000 else log_text
                await tracker.update_request_fields(
                    request_id, {"partial_logs": fallback_text}
                )
                logger.info(
                    f"Stored partial logs in MongoDB for cancelled request {request_id} "
                    f"({len(fallback_text)} chars)"
                    + (", also pushed to Loki" if pushed_to_loki else "")
                )
        except k8s_client.ApiException as log_err:
            if log_err.status != 404:
                logger.warning(f"Could not read logs from pod {pod_name}: {log_err}")
        except Exception as e:
            logger.warning(f"Failed to persist logs for {request_id}: {e}")

    # --- Delete K8s Job (job-mode only) ---
    # Pool-mode pods are NOT deleted here — monitor_execution's finally block
    # handles pod cleanup once it observes the terminal state.
    if job_name:
        try:
            await asyncio.to_thread(
                batch_v1.delete_namespaced_job,
                name=job_name,
                namespace=namespace,
                body=k8s_client.V1DeleteOptions(propagation_policy='Foreground'),
            )
            logger.info(f"Job {job_name} stopped by user {user.get('username')} for request {request_id}")
        except k8s_client.ApiException as e:
            if e.status != 404:
                logger.error(f"Failed to delete job {job_name}: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to stop job: {e.reason}")
            # 404 = job already gone, that's fine

    # --- Update request state ---
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
