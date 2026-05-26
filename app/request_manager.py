from typing import Dict, List, Tuple, Union, Any
from datetime import datetime, timezone, timedelta
from fastapi import WebSocket
import asyncio
import uuid
import logging
import os

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


def _serialize_for_json(data: Dict) -> Dict:
    """
    Convert datetime objects to ISO format strings for JSON serialization.
    This is needed for websocket messages that contain datetime fields.
    """
    serialized = {}
    for key, value in data.items():
        if isinstance(value, datetime):
            serialized[key] = value.isoformat()
        elif isinstance(value, dict):
            serialized[key] = _serialize_for_json(value)
        elif isinstance(value, list):
            serialized[key] = [_serialize_for_json(item) if isinstance(item, dict) else item for item in value]
        else:
            serialized[key] = value
    return serialized


class RequestTracker:
    def __init__(self, db_manager, email_service):
        self.db_manager = db_manager
        self.email_service = email_service
        self.collection_name = 'requests'
        self.active_websockets = {}
        self.retention_days = int(os.getenv('REQUESTS_RETENTION_PERIOD_IN_DAYS', '90'))  # Default to 90 days if not set
        self.change_stream_task = None  # Track the change stream task
        self._change_stream_started = False  # Track if change stream has been started

    def _ensure_change_stream_started(self):
        """
        Ensure the change stream watcher is started.
        This is called lazily when needed, ensuring the event loop is running.
        """
        if not self._change_stream_started:
            try:
                logger.info("Starting MongoDB change stream watcher for request updates")
                self.change_stream_task = asyncio.create_task(self._watch_request_changes())
                self._change_stream_started = True
            except RuntimeError as e:
                # Event loop not running yet, will retry on next call
                logger.debug(f"Could not start change stream yet (event loop not ready): {e}")

    async def _watch_request_changes(self):
        """
        Watch MongoDB change stream for updates to the requests collection.
        When any runner job updates a request, this app gets notified via the stream.
        This solves the distributed websocket problem without requiring Redis.

        NOTE: Requires MongoDB 4.0+ with replica set enabled.
        If change streams are not supported, this will log a warning and gracefully disable.
        """
        retry_delay = 5  # seconds
        max_retries = 3
        retry_count = 0

        while True:
            try:
                # Get the MongoDB collection directly
                collection = self.db_manager.db[self.collection_name]

                # Create pipeline to watch only for update operations
                pipeline = [
                    {'$match': {'operationType': 'update'}}
                ]

                logger.info(f"Opening change stream on '{self.collection_name}' collection")

                # Watch the collection for changes
                async with collection.watch(pipeline, full_document='updateLookup') as change_stream:
                    logger.info("✅ Change stream successfully opened - listening for updates")
                    retry_count = 0  # Reset retry count on successful connection

                    async for change in change_stream:
                        try:
                            # Extract information from the change event
                            full_document = change.get('fullDocument')
                            updated_fields = change.get('updateDescription', {}).get('updatedFields', {})

                            if not full_document:
                                continue

                            # Get request_id from the document, not from documentKey
                            # (documentKey contains _id, not request_id)
                            request_id = full_document.get('request_id')
                            request_type = full_document.get('request_type')

                            if not request_id:
                                logger.warning("Change detected but no request_id found in document")
                                continue

                            if not request_type:
                                logger.warning(f"Change detected for request {request_id} but no request_type found")
                                continue

                            logger.debug(f"Change stream detected update for request {request_id} (type: {request_type})")
                            logger.debug(f"Updated fields: {updated_fields}")

                            # Forward the update to local websockets on this app instance
                            await self._send_to_local_websockets(request_id, request_type, updated_fields)

                        except Exception as e:
                            logger.error(f"Error processing change stream event: {e}", exc_info=True)
                            # Continue processing other events
                            continue

            except Exception as e:
                retry_count += 1
                error_msg = str(e).lower()

                # Check if error is due to unsupported change streams
                if 'not supported' in error_msg or 'command not found' in error_msg or retry_count >= max_retries:
                    logger.warning(
                        "MongoDB Change Streams are not supported or unavailable. "
                        "Ensure MongoDB is running as a replica set (required for change streams). "
                        "Change stream watcher is now disabled. "
                        "Websocket updates will only work for requests on this app instance. "
                        "Consider enabling replica set or implementing client-side polling."
                    )
                    break  # Exit the loop, disable change stream watcher

                logger.error(f"Change stream connection error (attempt {retry_count}/{max_retries}): {e}", exc_info=True)
                logger.info(f"Reconnecting to change stream in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
                # Loop will automatically retry

    async def _send_to_local_websockets(self, request_id: str, request_type: str, update: Dict):
        """
        Send update to websockets on this app instance.
        This is called by the change stream watcher when MongoDB detects an update.
        """
        if request_type not in self.active_websockets:
            logger.debug(f"No active websockets for request type {request_type} on this instance")
            return

        # Serialize datetime objects to ISO format strings for JSON
        serialized_update = _serialize_for_json(update)

        # Create a snapshot to avoid modification during iteration
        websockets_snapshot = list(self.active_websockets[request_type].items())
        failed_websockets = []
        sent_count = 0

        for websocket, tracked_ids in websockets_snapshot:
            if request_id in tracked_ids:
                try:
                    await websocket.send_json({"request_id": request_id, "update": serialized_update})
                    logger.debug(f"Change stream update sent for {request_id} to WebSocket {id(websocket)}")
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Failed to send change stream update to websocket: {str(e)}")
                    failed_websockets.append((websocket, request_type))

        # Clean up failed websockets
        for websocket, req_type in failed_websockets:
            await self.unregister_websocket(websocket, req_type)

        if sent_count > 0:
            logger.debug(f"Sent update for {request_id} to {sent_count} local websocket(s)")

    async def create_request(self, requested_by: str, request_type: str, additional_details: Dict[str, Any] = None) -> Tuple[bool, Union[str, str]]:
        try:
            request_id = str(uuid.uuid4())
            request = {
                "request_id": request_id,
                "requested_by": requested_by,
                "requested_on": datetime.now(timezone.utc).isoformat(),
                "request_type": request_type,
                "state": "queued",
                "logs": None
            }
            if additional_details:
                request.update(additional_details)
            await self.db_manager.insert_document(self.collection_name, request)
            await self.broadcast_update(request_id, request)
            email_content = self.email_service.generate_dynamic_content(request)
            complete_email_content = self.email_service.generate_standard_html("User Details", email_content)
            self.email_service.send_email("User Information", complete_email_content, ["cirishafrank@gmail.com"])
            return True, request_id
        except Exception as e:
            return False, f"Failed to create request: {str(e)}"

    async def update_log_stream(self, request_id: str, log_group: str, log_stream: str) -> Tuple[bool, str]:
        try:
            log_stream_value = f"{log_group}:{log_stream}"
            await self.db_manager.update_document(
                self.collection_name,
                {"request_id": request_id},
                {"logs": log_stream_value}
            )
            await self.broadcast_update(request_id, {"log_stream": log_stream_value})
            return True, "Request's log stream updated successfully"
        except Exception as e:
            return False, f"Failed to update request's log stream: {str(e)}"

    async def update_log_details(self, request_id: str, log_details: str) -> Tuple[bool, str]:
        try:
            await self.db_manager.update_document(
                self.collection_name,
                {"request_id": request_id},
                {"logs": log_details}
            )
            return True, "Request's log detail updated successfully"
        except Exception as e:
            return False, f"Failed to update request's log detail: {str(e)}"

    TERMINAL_STATES = {
        "completed", "failed", "execution failed", "timed out", "cancelled",
        "benchmark succeeded", "benchmark failed",
        "rejected", "approval_timed_out",
    }

    async def update_job_name(self, request_id: str, job_name: str) -> Tuple[bool, str]:
        try:
            await self.db_manager.update_document(
                self.collection_name,
                {"request_id": request_id},
                {"job_name": job_name}
            )
            logger.debug(f"Job name stored for request {request_id}: {job_name}")
            return True, "Job name updated successfully"
        except Exception as e:
            return False, f"Failed to update job name: {str(e)}"

    async def update_request_state(self, request_id: str, new_state: str) -> Tuple[bool, str]:
        try:
            # Guard: once in a terminal state, only allow transitions to other terminal states
            current = await self.db_manager.find_document(self.collection_name, {"request_id": request_id})
            if current:
                current_state = current.get("state")
                if current_state in self.TERMINAL_STATES and new_state not in self.TERMINAL_STATES:
                    logger.warning(
                        f"Blocked state transition for {request_id}: '{current_state}' -> '{new_state}' "
                        f"(cannot move from terminal to non-terminal state)"
                    )
                    return True, f"Request already in terminal state: {current_state}"

            await self.db_manager.update_document(
                self.collection_name,
                {"request_id": request_id},
                {"state": new_state}
            )
            await self.broadcast_update(request_id, {"state": new_state})
            logger.debug(f"Request state updated successfully for {request_id} as {new_state}")
            return True, "Request state updated successfully"
        except Exception as e:
            return False, f"Failed to update request state: {str(e)}"

    async def update_error_details(self, request_id: str, error_message: str) -> Tuple[bool, str]:
        try:
            # Guard: don't overwrite error details if request already has a terminal state with an error
            current = await self.db_manager.find_document(self.collection_name, {"request_id": request_id})
            if current:
                current_state = current.get("state")
                existing_error = current.get("error")
                if current_state in self.TERMINAL_STATES and existing_error:
                    logger.warning(
                        f"Blocked error overwrite for {request_id}: state='{current_state}', "
                        f"keeping existing error='{existing_error[:100]}', rejected='{error_message[:100]}'"
                    )
                    return True, "Error details already set for terminal request"

            await self.db_manager.update_document(
                self.collection_name,
                {"request_id": request_id},
                {"error": error_message}
            )
            await self.broadcast_update(request_id, {"error": error_message})
            logger.debug(f"Error details updated for request {request_id}: {error_message}")
            return True, "Error details updated successfully"
        except Exception as e:
            return False, f"Failed to update error details: {str(e)}"

    async def update_discovery_config(self, request_id: str, discovery_config: Dict[str, str]) -> Tuple[bool, str]:
        """
        Store discovery configuration (queries) for a request.
        Used to avoid passing large queries via environment variables to Fargate.
        """
        try:
            await self.db_manager.update_document(
                self.collection_name,
                {"request_id": request_id},
                {"discovery_config": discovery_config}
            )
            logger.debug(f"Discovery config stored for request {request_id}")
            return True, "Discovery config updated successfully"
        except Exception as e:
            return False, f"Failed to update discovery config: {str(e)}"

    async def update_request_fields(self, request_id: str, fields: Dict[str, Any]) -> Tuple[bool, str]:
        """Update arbitrary fields on a request document (used for plan_output, approved_by, etc.)."""
        try:
            await self.db_manager.update_document(
                self.collection_name,
                {"request_id": request_id},
                fields,
            )
            await self.broadcast_update(request_id, fields)
            return True, "Request fields updated successfully"
        except Exception as e:
            return False, f"Failed to update request fields: {str(e)}"

    async def get_discovery_config(self, request_id: str) -> Tuple[bool, Union[Dict[str, str], str]]:
        """
        Retrieve discovery configuration (queries) for a request.
        Used by the discovery runner to fetch queries via HTTP instead of env vars.
        """
        try:
            request = await self.db_manager.find_document(
                self.collection_name,
                {"request_id": request_id}
            )

            if not request:
                return False, f"Request with ID {request_id} not found"

            discovery_config = request.get("discovery_config")

            if not discovery_config:
                return False, f"No discovery config found for request {request_id}"

            return True, discovery_config
        except Exception as e:
            logger.error(f"Error fetching discovery config for {request_id}: {str(e)}")
            return False, f"Failed to fetch discovery config: {str(e)}"

    async def list_requests(
        self,
        project_name: str,
        request_type: Union[str, List[str], None],  # ← CHANGED: Allow list or None
        page: int = 1,
        page_size: int = 10,
        custom_filter: Dict[str, Any] = None
    ) -> Tuple[bool, Union[Dict, str]]:
        try:
            skip = (page - 1) * page_size

            # Build filter criteria
            filter_criteria = {"project_name": project_name}

            # Handle request_type - can be string, list, or None
            if request_type:
                if isinstance(request_type, list):
                    filter_criteria["request_type"] = {"$in": request_type}  # ← NEW: MongoDB $in operator
                else:
                    filter_criteria["request_type"] = request_type  # ← EXISTING: Single type

            # Merging additional filter criteria, if provided
            if custom_filter:
                filter_criteria.update(custom_filter)

            # Fetching filtered requests
            all_requests = await self.db_manager.find_documents(
                self.collection_name,
                filter_criteria
            )

            total_count = len(all_requests)

            # Sorting the requests by 'requested_on' in descending order
            sorted_requests = sorted(all_requests, key=lambda x: x.get('requested_on', ''), reverse=True)
            paginated_requests = sorted_requests[skip:skip + page_size]

            return True, {
                "runs": paginated_requests,
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": -(-total_count // page_size)
            }
        except Exception as e:
            return False, f"Failed to list requests: {str(e)}"

    async def get_request_details(self, request_id: str) -> Tuple[bool, Union[Dict[str, Any], str]]:
        """
        Fetches the details of a request by its request_id.
        """
        try:
                # Retrieve the request details using the db_manager
            request_details = await self.db_manager.find_document(self.collection_name, {"request_id": request_id})

            if not request_details:
                return False, f"Request with ID {request_id} not found."

            return True, request_details
        except Exception as e:
            logger.error(f"Error fetching request details for {request_id}: {str(e)}")
            return False, f"Failed to fetch request details: {str(e)}"

    async def register_websocket(self, websocket: WebSocket, request_type: str):
        # Ensure change stream is started (lazy initialization)
        self._ensure_change_stream_started()

        if request_type not in self.active_websockets:
            self.active_websockets[request_type] = {}
        self.active_websockets[request_type][websocket] = set()
        logger.debug(f"WebSocket {id(websocket)} registered for {request_type}")

    async def unregister_websocket(self, websocket: WebSocket, request_type: str):
        if request_type in self.active_websockets:
            self.active_websockets[request_type].pop(websocket, None)
        logger.debug(f"WebSocket {id(websocket)} unregistered for {request_type}")

    async def update_tracked_requests(self, websocket: WebSocket, request_type: str, request_ids: List[str]):
        if request_type in self.active_websockets and websocket in self.active_websockets[request_type]:
            self.active_websockets[request_type][websocket] = set(request_ids)
        logger.debug(f"Updated tracked IDs for WebSocket {id(websocket)}: {request_ids}")

    async def broadcast_update(self, request_id: str, update: Dict, retry_attempts: int = 3, retry_delay: float = 0.5):
        """
        Broadcast update to websockets tracking the given request_id.

        NOTE: With MongoDB Change Streams enabled, this method now serves two purposes:
        1. Immediate local delivery to websockets on THIS Fargate task (fast path)
        2. The DB update will trigger the change stream, which notifies ALL other tasks

        This dual approach ensures:
        - Local websockets get updates immediately (no waiting for change stream)
        - Remote websockets (on other tasks) get updates via change stream
        - If local delivery fails, change stream provides redundancy
        """
        logger.debug("broadcast_update called")
        logger.debug(update)
        request = await self.db_manager.find_document(self.collection_name, {"request_id": request_id})
        logger.debug("Request found in broadcast")
        logger.debug(request)

        if not request:
            logger.warning(f"Request {request_id} not found in database")
            return

        request_type = request["request_type"]
        logger.debug(f"Request type: {request_type}")

        # Try to send immediately to local websockets (fast path)
        # The MongoDB change stream will handle distribution to other Fargate tasks
        for attempt in range(retry_attempts):
            if request_type in self.active_websockets:
            # Create a snapshot of websockets to iterate over
                websockets_snapshot = list(self.active_websockets[request_type].items())
                logger.debug(f"Attempt {attempt + 1}: Checking local websockets for {request_type}")

                sent_update = False
                failed_websockets = []

                # Iterate over the snapshot, not the live dictionary
                for websocket, tracked_ids in websockets_snapshot:
                    if request_id in tracked_ids:
                        try:
                            await websocket.send_json({"request_id": request_id, "update": update})
                            logger.debug(f"Local update sent for {request_id} to WebSocket {id(websocket)}")
                            sent_update = True
                        except Exception as e:
                            logger.error(f"Failed to send local update for {request_id}: {str(e)}")
                            failed_websockets.append((websocket, request_type))

                # Clean up failed websockets after iteration is complete
                for websocket, req_type in failed_websockets:
                    await self.unregister_websocket(websocket, req_type)

                if sent_update:
                    logger.debug("Local websockets notified, change stream will handle other tasks")
                    break
                else:
                    logger.debug(f"No local WebSocket tracking {request_id} on attempt {attempt + 1}")
                    await asyncio.sleep(retry_delay)
            else:
                logger.debug(f"No local websockets for {request_type}, change stream will notify other tasks")
                break  # No need to retry if no local websockets

    async def cleanup_requests(self) -> Tuple[bool, str]:
        """
        Deletes requests that are older than the retention period specified in REQUESTS_RETENTION_PERIOD_IN_DAYS.
        Returns a tuple of (success: bool, message: str).
        """
        try:
            # Calculate the cutoff date
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat()

            # Create query to find documents older than cutoff_date
            query = {
                "requested_on": {
                    "$lte": cutoff_date  # Less than or equal to cutoff date
                }
            }

            # Delete the old documents
            deleted_count = await self.db_manager.delete_documents(self.collection_name, query)

            message = f"Successfully deleted {deleted_count} requests older than {self.retention_days} days"
            logging.info(message)
            return True, message

        except Exception as e:
            error_message = f"Failed to cleanup old requests: {str(e)}"
            logging.error(error_message)
            return False, error_message
