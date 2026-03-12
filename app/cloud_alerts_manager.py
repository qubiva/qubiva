from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from enum import Enum
import logging

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class CloudPlatform(Enum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"


class AlertStatus(Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class CloudAlertManager:
    def __init__(self, db_manager, email_service=None, project_manager=None):
        self.db_manager = db_manager
        self.email_service = email_service
        self.project_manager = project_manager
        self.collection_name = "alerts"

    def _sanitize_azure_alert_id(self, alert_id: str) -> str:
        """
        Sanitize Azure alert ID by replacing problematic characters.
        This ensures consistent ID formatting for storage and lookup.
        """
        if not alert_id:
            return alert_id

        # Replace common problematic characters
        sanitized = alert_id.replace('/', '_')
        sanitized = sanitized.replace('+', '_')
        sanitized = sanitized.replace('=', '_')
        sanitized = sanitized.replace(' ', '_')
        sanitized = sanitized.replace(':', '_')
        sanitized = sanitized.replace('?', '_')
        sanitized = sanitized.replace('#', '_')
        sanitized = sanitized.replace('&', '_')
        sanitized = sanitized.replace('%', '_')
        return sanitized

    def _extract_cloud_alert_id(self, cloud_platform: str, alert_data: Dict) -> Optional[str]:
        """Extract the unique identifier based on cloud platform - WITHOUT timestamp for update behavior"""
        try:
            if cloud_platform == CloudPlatform.AWS.value:
                alarm_name = alert_data.get('AlarmName')
                aws_account = alert_data.get('AWSAccountId')
                region = alert_data.get('Region')

                if not all([alarm_name, aws_account, region]):
                    missing = []
                    if not alarm_name:
                        missing.append("AlarmName")
                    if not aws_account:
                        missing.append("AWSAccountId")
                    if not region:
                        missing.append("Region")
                    raise ValueError(f"Missing required fields: {', '.join(missing)}")

                # Remove timestamp to enable alert updates instead of duplicates
                return f"aws_{aws_account}_{region}_{alarm_name}"

            elif cloud_platform == CloudPlatform.GCP.value:
                # Handle nested incident structure properly
                incident_id = None
                if 'incident' in alert_data:
                    incident_id = alert_data['incident'].get('incident_id')
                elif 'incident_id' in alert_data:
                    incident_id = alert_data.get('incident_id')

                if incident_id:
                    return f"gcp_{incident_id}"
                raise ValueError("Missing incident_id in GCP alert data")

            elif cloud_platform == CloudPlatform.AZURE.value:
                alert_id = None

                # Handle Common Alert Schema
                if 'data' in alert_data and 'essentials' in alert_data['data']:
                    alert_id = alert_data['data']['essentials'].get('alertId')
                # Handle legacy metric alert schema
                elif 'context' in alert_data:
                    alert_id = alert_data['context'].get('id')
                # Handle activity log alerts
                elif 'data' in alert_data and 'context' in alert_data['data']:
                    activity_log = alert_data['data']['context'].get('activityLog', {})
                    alert_id = activity_log.get('resourceId') or activity_log.get('subscriptionId')
                # Direct alertId field (original format)
                elif 'alertId' in alert_data:
                    alert_id = alert_data.get('alertId')
                # Normalized format (snake_case from webhook normalization)
                elif 'alert_id' in alert_data:
                    alert_id = alert_data.get('alert_id')

                if alert_id:
                    sanitized_id = self._sanitize_azure_alert_id(alert_id)
                    return f"azure_{sanitized_id}"
                raise ValueError("Missing alertId or alert_id in Azure alert data")

            raise ValueError(f"Unsupported cloud platform: {cloud_platform}")

        except Exception as e:
            logger.error(f"Error extracting cloud alert ID: {str(e)}")
            raise ValueError(f"Could not extract alert ID from {cloud_platform} alert data: {str(e)}")

    def _is_resolved_by_cloud(self, cloud_platform: str, alert_data: Dict) -> bool:
        """Check if the alert is being marked as resolved by the cloud platform with enhanced detection."""
        try:
            if cloud_platform == CloudPlatform.AWS.value:
                return alert_data.get('NewStateValue') == 'OK'

            elif cloud_platform == CloudPlatform.GCP.value:
                # Handle nested incident structure (original format)
                if 'incident' in alert_data:
                    state = alert_data['incident'].get('state', '').lower()
                    return state == 'closed'
                # Handle normalized format (from webhook - already lowercase)
                return alert_data.get('state') == 'closed'

            elif cloud_platform == CloudPlatform.AZURE.value:
                # Handle normalized format (from webhook - already lowercase)
                monitor_condition = alert_data.get('monitor_condition', '')
                if monitor_condition == 'resolved':
                    return True
                elif monitor_condition == 'fired':
                    return False

                # Handle Common Alert Schema (original format)
                if 'data' in alert_data:
                    essentials = alert_data['data'].get('essentials', {})

                    # Primary resolution check - monitor condition
                    if essentials.get('monitorCondition') == 'Resolved':
                        return True

                    # Check alert context for resolution
                    alert_context = alert_data['data'].get('alertContext', {})
                    if alert_context.get('condition', {}).get('operator'):
                        # If we have condition data and monitor condition is "Fired", it's not resolved
                        if essentials.get('monitorCondition') == 'Fired':
                            return False

                    # Check nested status field
                    if alert_data['data'].get('status') == 'Resolved':
                        return True

                # Handle legacy metric alert schema
                if alert_data.get('status') == 'Resolved':
                    return True

                # Handle activity log alerts with nested context
                if 'data' in alert_data and 'context' in alert_data['data']:
                    activity_log = alert_data['data']['context'].get('activityLog', {})
                    status_value = activity_log.get('status', {})
                    if isinstance(status_value, dict) and status_value.get('value') == 'Resolved':
                        return True
                    elif isinstance(status_value, str) and status_value == 'Resolved':
                        return True

                return False

            return False

        except Exception as e:
            logger.error(f"Error checking cloud resolution status: {str(e)}")
            return False

    def _validate_alert_data(self, project_name: str, cloud_platform: str,
                           account_id: str, alert_data: Dict) -> Tuple[bool, str]:
        """Validate required fields and data types."""
        if not all([project_name, cloud_platform, account_id, alert_data]):
            return False, "Missing required fields"

        if not isinstance(alert_data, dict):
            return False, "Alert data must be a dictionary"

        if cloud_platform.lower() not in [p.value for p in CloudPlatform]:
            return False, f"Invalid cloud platform: {cloud_platform}"

        return True, ""

    async def _send_alert_notification_email(self, project_name: str, cloud_platform: str,
                                            account_id: str, cloud_alert_id: str,
                                            alert_data: Dict, notification_type: str):
        """
        Send email notification to all project members about alert status changes.

        Args:
            notification_type: 'new', 'resolved', or 'reopened'
        """
        if not self.email_service or not self.project_manager:
            logger.warning("Email service or project manager not configured - skipping alert notification")
            return

        try:
            # Get all project members
            members_success, members = await self.project_manager.get_project_members(project_name, search_query="")

            if not members_success or not members:
                logger.warning(f"No project members found for {project_name} - skipping alert notification")
                return

            # Extract alert summary/title based on cloud platform
            alert_summary = self._extract_alert_summary(cloud_platform, alert_data)
            severity = self._extract_severity(cloud_platform, alert_data)

            # Determine subject and title based on notification type
            if notification_type == 'new':
                subject = f"🚨 New Alert: {alert_summary}"
                title = "🚨 New Cloud Alert Detected"
                status_color = "#dc3545"  # Red
            elif notification_type == 'resolved':
                subject = f"✅ Alert Resolved: {alert_summary}"
                title = "✅ Cloud Alert Resolved"
                status_color = "#28a745"  # Green
            elif notification_type == 'reopened':
                subject = f"⚠️ Alert Reopened: {alert_summary}"
                title = "⚠️ Cloud Alert Reopened"
                status_color = "#ffc107"  # Yellow
            else:
                return

            # Build email content
            import os
            from app.app_config_manager import ConfigManager
            _base_url = ConfigManager.get_config('app', 'base_url')
            if not _base_url:
                _domain = os.getenv('DOMAIN')
                _base_url = f"https://{_domain}" if _domain else ''
            content = f"""
            <div style="background-color: {status_color}; color: white; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
                <h3 style="margin: 0; color: white;">Alert {notification_type.upper()}</h3>
            </div>
            <p><strong>Project:</strong> {project_name}</p>
            <p><strong>Cloud Platform:</strong> {cloud_platform.upper()}</p>
            <p><strong>Account ID:</strong> {account_id}</p>
            <p><strong>Alert ID:</strong> {cloud_alert_id}</p>
            <p><strong>Severity:</strong> <span style="background-color: #f0f0f0; padding: 4px 8px; border-radius: 3px; font-weight: 500;">{severity}</span></p>
            <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
            <p><strong>Summary:</strong></p>
            <div style="padding: 15px; background-color: #f9f9f9; border-left: 4px solid {status_color}; border-radius: 3px;">
                {alert_summary}
            </div>
            <p style="margin-top: 20px;"><a href="{_base_url}/dashboard/projects/{project_name}/alerts" style="display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">View All Alerts</a></p>
            """

            body = self.email_service.generate_standard_html(title=title, content=content)

            # Send email to all project members via BCC (privacy + single email)
            from anyio import to_thread
            success, msg = await to_thread.run_sync(
                self.email_service.send_email,
                subject,
                body,
                recipients=None,  # No direct recipients
                bcc=members  # Use BCC for all members
            )

            if success:
                logger.info(f"Alert notification ({notification_type}) sent to {len(members)} members of {project_name}")
            else:
                logger.error(f"Failed to send alert notification: {msg}")

        except Exception as e:
            logger.error(f"Error sending alert notification email: {str(e)}")

    def _extract_alert_summary(self, cloud_platform: str, alert_data: Dict) -> str:
        """Extract human-readable summary from alert data."""
        try:
            if cloud_platform == CloudPlatform.AWS.value:
                alarm_name = alert_data.get('AlarmName', 'Unknown Alarm')
                alarm_description = alert_data.get('AlarmDescription', '')
                return f"{alarm_name}" + (f" - {alarm_description}" if alarm_description else "")

            elif cloud_platform == CloudPlatform.AZURE.value:
                # Handle normalized format (from webhook)
                if 'summary' in alert_data:
                    return alert_data['summary']
                # Handle original Common Alert Schema
                if 'data' in alert_data:
                    essentials = alert_data['data'].get('essentials', {})
                    return essentials.get('alertRule', 'Unknown Alert')
                return alert_data.get('alert_rule', 'Unknown Alert')

            elif cloud_platform == CloudPlatform.GCP.value:
                # Handle normalized format
                if 'summary' in alert_data:
                    return alert_data['summary']
                # Handle original format
                if 'incident' in alert_data:
                    return alert_data['incident'].get('summary', 'Unknown Incident')
                return 'Unknown GCP Alert'

            return 'Alert detected'
        except Exception as e:
            logger.error(f"Error extracting alert summary: {str(e)}")
            return 'Alert detected'

    def _extract_severity(self, cloud_platform: str, alert_data: Dict) -> str:
        """Extract severity level from alert data."""
        try:
            if cloud_platform == CloudPlatform.AWS.value:
                # AWS doesn't have direct severity, use state
                state = alert_data.get('NewStateValue', 'UNKNOWN')
                return state

            elif cloud_platform == CloudPlatform.AZURE.value:
                # Normalized format
                if 'severity' in alert_data:
                    severity_map = {
                        'Sev0': 'Critical',
                        'Sev1': 'Error',
                        'Sev2': 'Warning',
                        'Sev3': 'Informational',
                        'Sev4': 'Verbose'
                    }
                    sev = alert_data['severity']
                    return severity_map.get(sev, sev)
                # Original format
                if 'data' in alert_data:
                    essentials = alert_data['data'].get('essentials', {})
                    return essentials.get('severity', 'Unknown')
                return 'Unknown'

            elif cloud_platform == CloudPlatform.GCP.value:
                # Normalized format
                if 'severity' in alert_data:
                    return alert_data['severity']
                # Original format
                if 'incident' in alert_data:
                    return alert_data['incident'].get('severity', 'Unknown')
                return 'Unknown'

            return 'Unknown'
        except Exception as e:
            logger.error(f"Error extracting severity: {str(e)}")
            return 'Unknown'

    async def create_or_update_alert(self, project_name: str, cloud_platform: str,
                                    account_id: str, alert_data: Dict[str, Any]) -> Dict:
        """
        Create a new alert or update existing one with enhanced time-based lifecycle logic.

        Logic:
        - Same alarm + existing OPEN alert → Update existing alert
        - Same alarm + RESOLVED alert < 1 hour old → Reopen existing alert
        - Same alarm + RESOLVED alert > 1 hour old → Create new alert (replace old one)
        - Cloud auto-resolution → Automatically mark as resolved
        """
        logger.debug(f"Processing alert for {cloud_platform}: {alert_data}")

        # Validate input data
        is_valid, error_message = self._validate_alert_data(
            project_name, cloud_platform, account_id, alert_data
        )
        if not is_valid:
            raise ValueError(error_message)

        cloud_alert_id = self._extract_cloud_alert_id(cloud_platform, alert_data)
        if not cloud_alert_id:
            raise ValueError(f"Could not extract alert ID from {cloud_platform} alert data")

        current_time = datetime.utcnow().isoformat()
        is_resolved_by_cloud = self._is_resolved_by_cloud(cloud_platform, alert_data)

        # Check if alert already exists
        existing_alert = await self.db_manager.find_document(
            self.collection_name,
            {
                "project_name": project_name,
                "cloud_platform": cloud_platform.lower(),
                "account_id": account_id,
                "cloud_alert_id": cloud_alert_id
            }
        )

        if existing_alert:
            # Handle existing alert based on current status and time
            if existing_alert["status"] == AlertStatus.OPEN.value:
                # Update existing open alert
                update_data = {
                    "alert": alert_data,
                    "updated_at": current_time
                }

                if is_resolved_by_cloud:
                    # Get existing resolution history
                    resolution_history = existing_alert.get("resolution_history", [])

                    update_data.update({
                        "status": AlertStatus.RESOLVED.value,
                        "resolved_at": current_time,
                        "resolved_by": "auto-resolved",
                        "resolution_note": "Automatically resolved by cloud platform",
                        "resolution_history": resolution_history  # Preserve existing history
                    })

                await self.db_manager.update_document(
                    self.collection_name,
                    {"cloud_alert_id": cloud_alert_id},
                    update_data
                )

                # Send email notification only when status changes to resolved
                if is_resolved_by_cloud:
                    await self._send_alert_notification_email(
                        project_name, cloud_platform, account_id, cloud_alert_id,
                        alert_data, 'resolved'
                    )

                action = "updated" if not is_resolved_by_cloud else "resolved"
                return {"message": f"Alert {action} successfully", "alert_id": cloud_alert_id}

            elif existing_alert["status"] == AlertStatus.RESOLVED.value:
                # Check if resolved recently (within 1 hour = 3600 seconds)
                resolved_time = datetime.fromisoformat(existing_alert["resolved_at"])
                time_diff = (datetime.utcnow() - resolved_time).total_seconds()

                if time_diff < 3600:  # Less than 1 hour ago
                    if not is_resolved_by_cloud:
                        # Preserve resolution history before reopening
                        resolution_history = existing_alert.get("resolution_history", [])
                        if existing_alert.get("resolved_by"):
                            resolution_history.append({
                                "resolved_at": existing_alert["resolved_at"],
                                "resolved_by": existing_alert["resolved_by"],
                                "resolution_note": existing_alert["resolution_note"],
                                "reopened_at": current_time
                            })

                        # Reopen recent resolved alert
                        update_data = {
                            "alert": alert_data,
                            "status": AlertStatus.OPEN.value,
                            "updated_at": current_time,
                            "resolved_at": None,
                            "resolved_by": None,
                            "resolution_note": None,
                            "resolution_history": resolution_history  # Preserve history
                        }

                        await self.db_manager.update_document(
                            self.collection_name,
                            {"cloud_alert_id": cloud_alert_id},
                            update_data
                        )

                        # Send email notification for reopened alert
                        await self._send_alert_notification_email(
                            project_name, cloud_platform, account_id, cloud_alert_id,
                            alert_data, 'reopened'
                        )

                        return {"message": "Alert reopened successfully (history preserved)", "alert_id": cloud_alert_id}
                    else:
                        # Update resolved alert with new data (cloud says it's still resolved)
                        update_data = {
                            "alert": alert_data,
                            "updated_at": current_time
                        }
                        await self.db_manager.update_document(
                            self.collection_name,
                            {"cloud_alert_id": cloud_alert_id},
                            update_data
                        )
                        return {"message": "Resolved alert updated successfully", "alert_id": cloud_alert_id}
                else:
                    # Create new alert (replace old resolved one - more than 1 hour old)
                    new_alert_doc = {
                        "project_name": project_name,
                        "cloud_platform": cloud_platform.lower(),
                        "account_id": account_id,
                        "cloud_alert_id": cloud_alert_id,
                        "alert": alert_data,
                        "status": AlertStatus.RESOLVED.value if is_resolved_by_cloud else AlertStatus.OPEN.value,
                        "created_at": current_time,
                        "updated_at": current_time,
                        "resolved_by": "auto-resolved" if is_resolved_by_cloud else None,
                        "resolved_at": current_time if is_resolved_by_cloud else None,
                        "resolution_note": "Automatically resolved by cloud platform" if is_resolved_by_cloud else None,
                        "resolution_history": []  # Initialize empty history for new alert
                    }

                    # Replace the old document using update_one_document with upsert
                    await self.db_manager.update_one_document(
                        self.collection_name,
                        {"cloud_alert_id": cloud_alert_id},
                        new_alert_doc,
                        upsert=True
                    )

                    # Send email notification only if new alert is OPEN (not already resolved)
                    if not is_resolved_by_cloud:
                        await self._send_alert_notification_email(
                            project_name, cloud_platform, account_id, cloud_alert_id,
                            alert_data, 'new'
                        )

                    return {"message": "New alert created (replaced old resolved alert)", "alert_id": cloud_alert_id}
        else:
            # Create completely new alert
            alert_doc = {
                "project_name": project_name,
                "cloud_platform": cloud_platform.lower(),
                "account_id": account_id,
                "cloud_alert_id": cloud_alert_id,
                "alert": alert_data,
                "status": AlertStatus.RESOLVED.value if is_resolved_by_cloud else AlertStatus.OPEN.value,
                "created_at": current_time,
                "updated_at": current_time,
                "resolved_by": "auto-resolved" if is_resolved_by_cloud else None,
                "resolved_at": current_time if is_resolved_by_cloud else None,
                "resolution_note": "Automatically resolved by cloud platform" if is_resolved_by_cloud else None,
                "resolution_history": []  # Initialize empty history for new alerts
            }

            await self.db_manager.insert_document(self.collection_name, alert_doc)

            # Send email notification only if new alert is OPEN (not already resolved)
            if not is_resolved_by_cloud:
                await self._send_alert_notification_email(
                    project_name, cloud_platform, account_id, cloud_alert_id,
                    alert_data, 'new'
                )

            status = "resolved" if is_resolved_by_cloud else "open"
            return {"message": f"Alert created successfully ({status})", "alert_id": cloud_alert_id}

    async def list_alerts(self,
                     cloud_platform: Optional[str] = None,
                     status: Optional[str] = None,
                     account_id: Optional[str] = None,
                     project_name: Optional[str] = None,
                     start_time: Optional[str] = None,
                     end_time: Optional[str] = None,
                     page: int = 1,
                     page_size: int = 50) -> Dict[str, Any]:
        """List alerts with filtering and pagination."""
        query = {}

        if cloud_platform:
            query["cloud_platform"] = cloud_platform.lower()
        if status:
            query["status"] = status
        if account_id:
            query["account_id"] = account_id
        if project_name:
            query["project_name"] = project_name

        if start_time or end_time:
            query["created_at"] = {}
            if start_time:
                query["created_at"]["$gte"] = start_time
            if end_time:
                query["created_at"]["$lte"] = end_time

        skip = (page - 1) * page_size

        # Get all documents and sort them: unresolved first, then by latest created_at
        logger.debug(f"Alert query: {query}")
        all_documents = await self.db_manager.find_documents(self.collection_name, query)
        # Sort by: status (resolved=1, open=0) and created_at, both descending
        # With reverse=True: higher values first. So resolved(1) > open(0), BUT we want open first
        # Solution: Use resolved=0, open=1 so open sorts higher
        sorted_documents = sorted(
            all_documents,
            key=lambda x: (1 if x.get('status') == 'open' else 0, x.get('created_at', '')),
            reverse=True  # Reverse gives us: open(1) before resolved(0), and newer dates before older
        )

        total_documents = len(sorted_documents)
        paginated_documents = sorted_documents[skip:skip + page_size]

        total_pages = (total_documents + page_size - 1) // page_size

        return {
            "alerts": paginated_documents,
            "pagination": {
                "current_page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_items": total_documents,
                "has_next": page < total_pages,
                "has_previous": page > 1
            }
        }

    async def resolve_alert(self, project_name: str, account_id: str,
                          cloud_alert_id: str, resolved_by: str,
                          resolution_note: str) -> bool:
        """Mark an alert as resolved with history preservation."""
        if not resolution_note:
            raise ValueError("Resolution note is required")

        query = {
            "project_name": project_name,
            "account_id": account_id,
            "cloud_alert_id": cloud_alert_id,
            "status": AlertStatus.OPEN.value  # Only allow resolving open alerts
        }

        # Get existing alert to preserve any existing resolution history
        existing_alert = await self.db_manager.find_document(self.collection_name, {
            "cloud_alert_id": cloud_alert_id,
            "project_name": project_name,
            "account_id": account_id
        })

        if not existing_alert:
            return False

        # Initialize resolution_history if it doesn't exist
        resolution_history = existing_alert.get("resolution_history", [])

        update = {
            "status": AlertStatus.RESOLVED.value,
            "resolved_by": resolved_by,
            "resolved_at": datetime.utcnow().isoformat(),
            "resolution_note": resolution_note,
            "updated_at": datetime.utcnow().isoformat(),
            "resolution_history": resolution_history  # Preserve existing history
        }

        result = await self.db_manager.update_document(self.collection_name, query, update)

        # Send email notification if alert was successfully resolved
        if result > 0:
            cloud_platform = existing_alert.get('cloud_platform', 'unknown')
            alert_data = existing_alert.get('alert', {})
            await self._send_alert_notification_email(
                project_name, cloud_platform, account_id, cloud_alert_id,
                alert_data, 'resolved'
            )

        return result > 0

    async def get_alert_stats(self, project_name: Optional[str] = None,
                            account_id: Optional[str] = None) -> Dict[str, Any]:
        """Get alert statistics."""
        query = {}
        if project_name:
            query["project_name"] = project_name
        if account_id:
            query["account_id"] = account_id

        alerts = await self.db_manager.find_documents(self.collection_name, query)

        stats = {
            "total": len(alerts),
            "open": len([a for a in alerts if a["status"] == AlertStatus.OPEN.value]),
            "resolved": len([a for a in alerts if a["status"] == AlertStatus.RESOLVED.value]),
            "by_platform": {
                CloudPlatform.AWS.value: 0,
                CloudPlatform.GCP.value: 0,
                CloudPlatform.AZURE.value: 0
            }
        }

        for alert in alerts:
            platform = alert.get("cloud_platform")
            if platform in stats["by_platform"]:
                stats["by_platform"][platform] += 1

        return stats

    async def get_alert_history(self, cloud_alert_id: str) -> Optional[Dict]:
        """Get a specific alert by its cloud alert ID."""
        return await self.db_manager.find_document(
            self.collection_name,
            {"cloud_alert_id": cloud_alert_id}
        )
