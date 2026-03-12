import uuid
import os
import socket
import datetime
import logging
import asyncio
from croniter import croniter

import httpx

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class Scheduler:
    """
    In-app scheduler using asyncio tasks and MongoDB for persistence.
    Replaces AWS EventBridge with a self-contained scheduling system.

    Supports:
    - rate(N minutes/hours/days) — interval-based execution
    - cron(min hour dom month dow [year]) — AWS EventBridge cron format
    - Standard 5-field cron: "*/5 * * * *"
    - Simple: "30m", "1h", "1d"

    Schedules are stored in MongoDB and executed via authenticated HTTP calls.

    Leader election ensures only one pod runs schedules when scaled horizontally.
    Uses a MongoDB distributed lock with heartbeat/TTL pattern.
    """

    LOCK_COLLECTION = "system_locks"
    LOCK_NAME = "scheduler_leader"
    LOCK_TTL_SECONDS = 60
    HEARTBEAT_INTERVAL = 15
    LEADER_CHECK_INTERVAL = 30

    def __init__(self, db_manager, email_service):
        self.db_manager = db_manager
        self.collection_name = "schedules"
        self.email_service = email_service
        self._running_tasks = {}  # schedule_id -> asyncio.Task
        self._leader = False
        self._leader_task = None  # the leader lifecycle background task
        self._pod_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"

    # ─── Leader Election ───────────────────────────────────────────────

    async def start_leader_election(self):
        """Start the leader election background loop. Call once at app startup."""
        self._leader_task = asyncio.create_task(self._leader_lifecycle())

    async def stop_leader_election(self):
        """Stop leader election and release the lock."""
        if self._leader_task:
            self._leader_task.cancel()
            try:
                await self._leader_task
            except asyncio.CancelledError:
                pass
        if self._leader:
            await self._release_lock()
            await self._stop_all_schedules()
            self._leader = False

    async def _try_acquire_lock(self) -> bool:
        """
        Atomically try to acquire the scheduler leader lock.
        Succeeds if: lock doesn't exist, lock expired, or we already hold it.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now + datetime.timedelta(seconds=self.LOCK_TTL_SECONDS)

        result = await self.db_manager.find_one_and_update(
            self.LOCK_COLLECTION,
            {
                "lock_name": self.LOCK_NAME,
                "$or": [
                    {"expires_at": {"$lt": now}},       # Lock expired
                    {"holder_id": self._pod_id},         # We already hold it
                ]
            },
            {
                "$set": {
                    "lock_name": self.LOCK_NAME,
                    "holder_id": self._pod_id,
                    "expires_at": expires_at,
                    "heartbeat_at": now,
                }
            },
            upsert=False,
            return_new=True,
        )

        if result and result.get("holder_id") == self._pod_id:
            return True

        # Lock document might not exist yet — try to create it
        if result is None:
            existing = await self.db_manager.find_document(
                self.LOCK_COLLECTION, {"lock_name": self.LOCK_NAME}
            )
            if existing is None:
                # No lock document at all — create one
                try:
                    await self.db_manager.insert_document(self.LOCK_COLLECTION, {
                        "lock_name": self.LOCK_NAME,
                        "holder_id": self._pod_id,
                        "expires_at": expires_at,
                        "heartbeat_at": now,
                    })
                    return True
                except Exception:
                    # Another pod beat us to it — that's fine
                    return False

        return False

    async def _refresh_heartbeat(self) -> bool:
        """Refresh the lock TTL. Returns False if we lost the lock."""
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now + datetime.timedelta(seconds=self.LOCK_TTL_SECONDS)

        result = await self.db_manager.find_one_and_update(
            self.LOCK_COLLECTION,
            {
                "lock_name": self.LOCK_NAME,
                "holder_id": self._pod_id,
            },
            {
                "$set": {
                    "expires_at": expires_at,
                    "heartbeat_at": now,
                }
            },
            return_new=True,
        )
        return result is not None and result.get("holder_id") == self._pod_id

    async def _release_lock(self):
        """Release the leader lock so another pod can take over immediately."""
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            # Set expires_at to the past so next pod can acquire immediately
            await self.db_manager.find_one_and_update(
                self.LOCK_COLLECTION,
                {
                    "lock_name": self.LOCK_NAME,
                    "holder_id": self._pod_id,
                },
                {
                    "$set": {
                        "expires_at": now - datetime.timedelta(seconds=1),
                        "holder_id": "released",
                    }
                },
            )
            logger.info(f"Released scheduler leader lock (pod: {self._pod_id})")
        except Exception as e:
            logger.warning(f"Failed to release leader lock: {e}")

    async def _leader_lifecycle(self):
        """
        Main leader election loop. Runs for the entire lifetime of the pod.
        - If leader: refresh heartbeat, run schedules
        - If not leader: periodically attempt to acquire
        """
        logger.info(f"Scheduler leader election started (pod: {self._pod_id})")

        while True:
            try:
                if self._leader:
                    # We are the leader — refresh heartbeat
                    still_leader = await self._refresh_heartbeat()
                    if not still_leader:
                        logger.warning("Lost scheduler leader lock! Stopping all schedule tasks.")
                        await self._stop_all_schedules()
                        self._leader = False
                    await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                else:
                    # We are not the leader — try to acquire
                    acquired = await self._try_acquire_lock()
                    if acquired:
                        logger.info(f"Acquired scheduler leader lock (pod: {self._pod_id})")
                        self._leader = True
                        await self.sync_schedules()
                    else:
                        lock_doc = await self.db_manager.find_document(
                            self.LOCK_COLLECTION, {"lock_name": self.LOCK_NAME}
                        )
                        current_leader = lock_doc.get("holder_id", "unknown") if lock_doc else "none"
                        logger.debug(f"Not leader. Current leader: {current_leader}")
                    await asyncio.sleep(self.LEADER_CHECK_INTERVAL)

            except asyncio.CancelledError:
                logger.info("Leader election task cancelled")
                break
            except Exception as e:
                logger.error(f"Leader election error: {e}")
                await asyncio.sleep(self.LEADER_CHECK_INTERVAL)

    async def _stop_all_schedules(self):
        """Cancel all running schedule tasks."""
        for schedule_id, task in list(self._running_tasks.items()):
            task.cancel()
        self._running_tasks.clear()
        logger.info("All schedule tasks stopped")

    @property
    def is_leader(self) -> bool:
        return self._leader

    # ─── Frequency Parsing ─────────────────────────────────────────────

    def _parse_frequency(self, frequency: str) -> dict:
        """
        Parse schedule frequency string into a typed descriptor.

        Returns:
            {"type": "rate", "interval_seconds": int}
            {"type": "cron", "expression": str}  (standard 5-field cron)

        Raises ValueError if expression is invalid.
        """
        freq = frequency.strip()
        freq_lower = freq.lower()

        # rate() format: rate(5 minutes), rate(1 hour), rate(1 day)
        if freq_lower.startswith('rate(') and freq_lower.endswith(')'):
            inner = freq_lower[5:-1].strip()
            parts = inner.split()
            if len(parts) == 2:
                try:
                    value = int(parts[0])
                except ValueError:
                    raise ValueError(f"Invalid rate value: {parts[0]}")
                unit = parts[1].rstrip('s')  # Remove plural s
                if unit == 'minute':
                    return {"type": "rate", "interval_seconds": value * 60}
                elif unit == 'hour':
                    return {"type": "rate", "interval_seconds": value * 3600}
                elif unit == 'day':
                    return {"type": "rate", "interval_seconds": value * 86400}
                else:
                    raise ValueError(f"Invalid rate unit: {parts[1]}. Use minutes, hours, or days.")
            raise ValueError(f"Invalid rate format: {frequency}. Use rate(N minutes/hours/days).")

        # cron() format: AWS EventBridge cron(min hour dom month dow year)
        if freq_lower.startswith('cron(') and freq_lower.endswith(')'):
            inner = freq[5:-1].strip()  # Keep original case for safety
            standard_cron = self._aws_cron_to_standard(inner)
            # Validate with croniter
            if not croniter.is_valid(standard_cron):
                raise ValueError(f"Invalid cron expression: {frequency} (converted to: {standard_cron})")
            return {"type": "cron", "expression": standard_cron}

        # Simple format: 30m, 1h, 1d
        if freq_lower.endswith('m') and freq_lower[:-1].isdigit():
            return {"type": "rate", "interval_seconds": int(freq_lower[:-1]) * 60}
        elif freq_lower.endswith('h') and freq_lower[:-1].isdigit():
            return {"type": "rate", "interval_seconds": int(freq_lower[:-1]) * 3600}
        elif freq_lower.endswith('d') and freq_lower[:-1].isdigit():
            return {"type": "rate", "interval_seconds": int(freq_lower[:-1]) * 86400}

        # Try as raw 5-field cron expression
        if croniter.is_valid(freq):
            return {"type": "cron", "expression": freq}

        raise ValueError(
            f"Invalid schedule expression: {frequency}. "
            "Use rate(N minutes/hours/days), cron(min hour dom month dow [year]), "
            "standard cron (e.g. '0 12 * * *'), or simple format (30m, 1h, 1d)."
        )

    @staticmethod
    def _aws_cron_to_standard(aws_cron: str) -> str:
        """
        Convert AWS EventBridge 6-field cron to standard 5-field cron.

        AWS:      minute hour day-of-month month day-of-week year
        Standard: minute hour day-of-month month day-of-week

        AWS uses '?' for "no specific value" in day-of-month or day-of-week.
        Standard cron uses '*' for that purpose.
        """
        fields = aws_cron.split()

        # If 6 fields (AWS format), drop the year field
        if len(fields) == 6:
            fields = fields[:5]

        # Replace '?' with '*' (AWS-specific placeholder)
        fields = ['*' if f == '?' else f for f in fields]

        return ' '.join(fields)

    def _get_next_run_time(self, parsed: dict, base_time: datetime.datetime = None) -> datetime.datetime:
        """Calculate the next execution time based on the schedule type."""
        now = base_time or datetime.datetime.now(datetime.timezone.utc)

        if parsed["type"] == "rate":
            return now + datetime.timedelta(seconds=parsed["interval_seconds"])
        elif parsed["type"] == "cron":
            cron = croniter(parsed["expression"], now)
            return cron.get_next(datetime.datetime).replace(tzinfo=datetime.timezone.utc)

    def _get_auth_headers(self) -> dict:
        """Build headers for authenticated self-calls."""
        headers = {'Content-Type': 'application/json'}
        internal_api_key = os.environ.get('INTERNAL_API_KEY')
        if internal_api_key:
            headers['X-Internal-Api-Key'] = internal_api_key
        return headers

    # ─── Schedule Execution ────────────────────────────────────────────

    async def _execute_schedule(self, schedule_id: str, endpoint: str,
                                payload: dict, frequency: str):
        """Background task that executes a schedule on its frequency."""
        try:
            parsed = self._parse_frequency(frequency)
        except ValueError as e:
            logger.error(f"Schedule {schedule_id} has invalid frequency '{frequency}': {e}")
            return

        base_url = os.environ.get('QUBIVA_API_ENDPOINT', 'http://localhost:8000').rstrip('/')
        full_url = base_url + endpoint
        headers = self._get_auth_headers()

        last_scheduled_time = None  # Track the scheduled time to maintain cadence

        while True:
            try:
                # Check we're still the leader before each iteration
                if not self._leader:
                    logger.info(f"Schedule {schedule_id}: no longer leader, stopping task")
                    break

                now = datetime.datetime.now(datetime.timezone.utc)

                if last_scheduled_time is None:
                    # First iteration: compute next run anchored to created_at for rate schedules
                    schedule_doc = await self.get_schedule(schedule_id)

                    if parsed["type"] == "rate" and schedule_doc:
                        # Anchor to created_at so cadence never drifts
                        created_at = schedule_doc.get('created_at')
                        if created_at:
                            if isinstance(created_at, str):
                                created_at = datetime.datetime.fromisoformat(created_at)
                            if created_at.tzinfo is None:
                                created_at = created_at.replace(tzinfo=datetime.timezone.utc)
                            interval = parsed["interval_seconds"]
                            # Calculate how many intervals have elapsed since creation
                            elapsed = (now - created_at).total_seconds()
                            intervals_passed = int(elapsed / interval)
                            next_run = created_at + datetime.timedelta(seconds=(intervals_passed + 1) * interval)
                        else:
                            next_run = self._get_next_run_time(parsed, now)
                    elif parsed["type"] == "cron":
                        next_run = self._get_next_run_time(parsed, now)
                    else:
                        next_run = self._get_next_run_time(parsed, now)
                else:
                    # Subsequent iterations: anchor to last scheduled time, not current time
                    if parsed["type"] == "rate":
                        next_run = last_scheduled_time + datetime.timedelta(seconds=parsed["interval_seconds"])
                    else:
                        next_run = self._get_next_run_time(parsed, now)

                last_scheduled_time = next_run

                sleep_seconds = max(0, (next_run - now).total_seconds())

                # Store next execution time in MongoDB
                await self.db_manager.update_document(
                    self.collection_name,
                    {"schedule_id": schedule_id},
                    {"next_execution": next_run.isoformat()}
                )

                logger.info(
                    f"Schedule {schedule_id}: next execution at {next_run.isoformat()} "
                    f"(in {sleep_seconds:.0f}s)"
                )
                await asyncio.sleep(sleep_seconds)

                # Re-check if schedule is still enabled (may have been disabled during sleep)
                schedule = await self.get_schedule(schedule_id)
                if not schedule or schedule.get('status') != 'enabled':
                    logger.info(f"Schedule {schedule_id} is no longer enabled, stopping")
                    break

                # Re-check leader status after sleep
                if not self._leader:
                    logger.info(f"Schedule {schedule_id}: lost leadership during sleep, stopping")
                    break

                # Execute the HTTP call with auth
                logger.info(f"Schedule {schedule_id}: executing {endpoint}")
                request_headers = {**headers, 'X-Schedule-ID': schedule_id}
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(
                        full_url,
                        json=payload,
                        headers=request_headers,
                    )

                    if response.status_code < 400:
                        logger.info(f"Schedule {schedule_id} executed successfully: {response.status_code}")
                    else:
                        logger.warning(
                            f"Schedule {schedule_id} execution returned {response.status_code}: "
                            f"{response.text[:200]}"
                        )

                # Update last execution time
                await self.db_manager.update_document(
                    self.collection_name,
                    {"schedule_id": schedule_id},
                    {"last_executed": datetime.datetime.now(datetime.timezone.utc).isoformat()}
                )

            except asyncio.CancelledError:
                logger.info(f"Schedule {schedule_id} task cancelled")
                break
            except Exception as e:
                logger.error(f"Error executing schedule {schedule_id}: {e}")
                # Continue running; will retry on next interval

    # ─── CRUD Operations ───────────────────────────────────────────────

    async def create_schedule(self, endpoint, payload, frequency, project_name, username):
        """Create a new schedule in MongoDB and start the background task if leader."""
        # Validate the frequency expression before saving (ValueError propagates to caller)
        parsed = self._parse_frequency(frequency)

        schedule_id = str(uuid.uuid4())[:8]
        payload_to_store = payload.copy()
        payload_to_store.pop("schedule", None)

        now = datetime.datetime.now(datetime.timezone.utc)
        next_run = self._get_next_run_time(parsed, now)

        document = {
            "schedule_id": schedule_id,
            "requested_by": username,
            "endpoint": endpoint,
            "payload": payload_to_store,
            "frequency": frequency,
            "frequency_type": parsed["type"],
            "project_name": project_name,
            "status": "enabled",
            "created_at": now.isoformat(),
            "last_modified": now.isoformat(),
            "next_execution": next_run.isoformat(),
        }

        try:
            await self.db_manager.insert_document(self.collection_name, document)
            logger.info(f"Schedule saved in MongoDB: {schedule_id} ({parsed['type']})")
        except Exception as e:
            logger.error(f"Failed to save schedule in MongoDB: {e}")
            raise RuntimeError("Failed to save schedule in database")

        # Only start background task if this pod is the leader
        if self._leader:
            task = asyncio.create_task(
                self._execute_schedule(schedule_id, endpoint, payload_to_store, frequency)
            )
            self._running_tasks[schedule_id] = task
            logger.info(f"Started schedule task: {schedule_id}, next run: {next_run.isoformat()}")
        else:
            logger.info(f"Schedule {schedule_id} saved. Leader pod will pick it up on next sync.")

        return {"status": "success", "schedule_id": schedule_id, "next_execution": next_run.isoformat()}

    async def delete_project_schedules(self, project_name: str) -> dict:
        """Delete all schedules for a project."""
        deleted_count = 0
        failed_rules = []

        try:
            schedules = await self.db_manager.find_documents(
                self.collection_name,
                {"project_name": project_name}
            )

            # Cancel running tasks
            for schedule in schedules:
                sid = schedule.get("schedule_id")
                if sid in self._running_tasks:
                    self._running_tasks[sid].cancel()
                    del self._running_tasks[sid]
                deleted_count += 1

            # Delete from MongoDB
            try:
                await self.db_manager.delete_documents(
                    self.collection_name,
                    {"project_name": project_name}
                )
                logger.info(f"Cleaned up MongoDB schedules for project: {project_name}")
            except Exception as e:
                logger.error(f"Failed to cleanup MongoDB schedules: {e}")
                failed_rules.append({
                    "schedule_id": "mongodb_cleanup",
                    "error": str(e)
                })

            result = {
                "status": "success" if not failed_rules else "partial_success",
                "deleted_count": deleted_count,
                "failed_count": len(failed_rules),
                "project_name": project_name
            }

            if failed_rules:
                result["failures"] = failed_rules

            return result

        except Exception as e:
            logger.error(f"Unexpected error in delete_project_schedules: {e}")
            return {
                "status": "error",
                "error": str(e),
                "project_name": project_name,
                "deleted_count": deleted_count,
                "failed_count": len(failed_rules) + 1
            }

    async def delete_schedule(self, schedule_id, project_name):
        """Delete a schedule from MongoDB and cancel its task."""
        # Cancel running task
        if schedule_id in self._running_tasks:
            self._running_tasks[schedule_id].cancel()
            del self._running_tasks[schedule_id]
            logger.info(f"Cancelled task for schedule: {schedule_id}")

        # Delete from MongoDB
        try:
            result = await self.db_manager.delete_document(self.collection_name, {"schedule_id": schedule_id})
            if result == 0:
                logger.warning(f"No MongoDB entry found for schedule: {schedule_id}")
        except Exception as e:
            logger.error(f"Failed to delete schedule from MongoDB: {e}")
            raise RuntimeError("Failed to delete schedule from database")

        return {"status": "success", "schedule_id": schedule_id}

    async def update_schedule_status(self, schedule_id, project_name, new_status):
        """Pause or resume a schedule."""
        try:
            current_schedule = await self.get_schedule(schedule_id)
            if not current_schedule:
                raise RuntimeError(f"Schedule {schedule_id} not found")
        except Exception as e:
            logger.error(f"Failed to get current schedule state: {e}")
            raise RuntimeError("Failed to get current schedule state")

        try:
            update_fields = {
                "status": new_status,
                "last_modified": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }

            if new_status == "disabled":
                # Cancel running task
                if schedule_id in self._running_tasks:
                    self._running_tasks[schedule_id].cancel()
                    del self._running_tasks[schedule_id]
                update_fields["next_execution"] = None

            elif new_status == "enabled":
                # Calculate next execution time
                try:
                    parsed = self._parse_frequency(current_schedule['frequency'])
                    next_run = self._get_next_run_time(parsed)
                    update_fields["next_execution"] = next_run.isoformat()
                except ValueError:
                    pass

                # Start task if leader and not already running
                if self._leader and schedule_id not in self._running_tasks:
                    task = asyncio.create_task(
                        self._execute_schedule(
                            schedule_id,
                            current_schedule['endpoint'],
                            current_schedule['payload'],
                            current_schedule['frequency']
                        )
                    )
                    self._running_tasks[schedule_id] = task

            await self.db_manager.update_document(
                self.collection_name,
                {"schedule_id": schedule_id},
                update_fields
            )

        except Exception as e:
            logger.error(f"Unexpected error updating schedule status: {e}")
            raise RuntimeError(f"Failed to update schedule status: {str(e)}")

        return {"status": "success", "schedule_id": schedule_id, "new_status": new_status}

    async def list_schedules(self, project_name, filters=None):
        """List schedules with flexible filtering."""
        try:
            query = {"project_name": project_name}

            if filters:
                for key, value in filters.items():
                    if value is not None:
                        query[key] = value

            logger.debug(f"Executing query with filters: {query}")
            schedules = await self.db_manager.find_documents(self.collection_name, query)
            logger.info(f"Schedules retrieved: {len(schedules)}")

            return schedules
        except Exception as e:
            logger.error(f"Failed to retrieve schedules: {e}")
            raise RuntimeError(f"Failed to retrieve schedules from database: {str(e)}")

    async def get_schedule(self, schedule_id):
        """Get a specific schedule by ID."""
        try:
            query = {"schedule_id": schedule_id}
            schedule = await self.db_manager.find_document(self.collection_name, query)

            if not schedule:
                logger.debug(f"No schedule found with ID: {schedule_id}")
                return None

            logger.debug(f"Retrieved schedule: {schedule}")
            return schedule

        except Exception as e:
            logger.error(f"Failed to retrieve schedule {schedule_id}: {e}")
            raise RuntimeError(f"Failed to retrieve schedule from database: {str(e)}")

    async def sync_schedules(self):
        """
        Restore running schedule tasks from MongoDB on startup or after acquiring leadership.
        Only the leader pod should call this.

        If a schedule missed its execution window (next_execution < now),
        it runs immediately on the next cycle.
        """
        if not self._leader:
            logger.debug("sync_schedules called but not leader, skipping")
            return

        try:
            schedules = await self.db_manager.find_all(self.collection_name)

            restored_count = 0
            for schedule in schedules:
                if schedule.get('status') == 'enabled':
                    schedule_id = schedule['schedule_id']
                    if schedule_id not in self._running_tasks:
                        task = asyncio.create_task(
                            self._execute_schedule(
                                schedule_id,
                                schedule['endpoint'],
                                schedule.get('payload', {}),
                                schedule['frequency']
                            )
                        )
                        self._running_tasks[schedule_id] = task
                        restored_count += 1

            logger.info(f"Restored {restored_count} schedule tasks from MongoDB")

        except Exception as e:
            logger.error(f"Sync process failed: {e}")
            raise RuntimeError("Failed to sync schedules from database")
