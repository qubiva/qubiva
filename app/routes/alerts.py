"""
Cloud alert webhook and alert management routes for Qubiva.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.deps import (
    alerts_manager,
    alert_configurator as _alert_configurator_default,
    authenticator,
    db_manager,
    project_manager,
    get_app_base_url,
)
from app.models import Models
from app.auth_helpers import authenticate_http_user, authenticate_webhook
from app.alert_configurator import AlertConfigurator
from app.decorators import permissions

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


# ---- Webhook verification helpers ----

async def verify_sns_signature(payload: dict) -> bool:
    """
    Verify the signature of an AWS SNS message to ensure authenticity.
    """
    try:
        import base64
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from urllib.parse import urlparse
        import httpx

        # Validate SigningCertURL is from AWS
        signing_cert_url = payload.get("SigningCertURL")
        if not signing_cert_url:
            logger.error("SNS message missing SigningCertURL")
            return False

        parsed_url = urlparse(signing_cert_url)
        if not parsed_url.hostname or not parsed_url.hostname.endswith('.amazonaws.com'):
            logger.error(f"Invalid SigningCertURL domain: {parsed_url.hostname}")
            return False

        if parsed_url.scheme != 'https':
            logger.error(f"SigningCertURL must use HTTPS: {signing_cert_url}")
            return False

        # Download the signing certificate
        logger.debug(f"Downloading signing certificate from: {signing_cert_url}")
        async with httpx.AsyncClient() as client:
            cert_response = await client.get(signing_cert_url)
            if cert_response.status_code != 200:
                logger.error(f"Failed to download signing certificate: {cert_response.status_code}")
                return False

        # Load the certificate
        logger.debug(f"Loading signing certificate, size: {len(cert_response.content)} bytes")
        signing_cert = x509.load_pem_x509_certificate(cert_response.content)
        logger.debug("Signing certificate loaded successfully")

        # Decode the signature
        signature = payload.get("Signature")
        if not signature:
            logger.error("SNS message missing Signature")
            return False

        logger.debug(f"Decoding signature, length: {len(signature)}")
        decoded_signature = base64.b64decode(signature)
        logger.debug(f"Decoded signature, length: {len(decoded_signature)} bytes")

        # Determine hash algorithm based on signature version
        signature_version = payload.get("SignatureVersion", "1")
        signature_hash = hashes.SHA1() if signature_version == "1" else hashes.SHA256()
        logger.debug(f"Using signature version: {signature_version}, hash algorithm: {type(signature_hash).__name__}")

        # Build the canonical string to sign
        message_type = payload.get('Type')
        logger.debug(f"Building canonical string for message type: {message_type}")

        if message_type in ['SubscriptionConfirmation', 'UnsubscribeConfirmation']:
            string_to_sign = (
                f"Message\n{payload['Message']}\n"
                f"MessageId\n{payload['MessageId']}\n"
                f"SubscribeURL\n{payload['SubscribeURL']}\n"
                f"Timestamp\n{payload['Timestamp']}\n"
                f"Token\n{payload['Token']}\n"
                f"TopicArn\n{payload['TopicArn']}\n"
                f"Type\n{payload['Type']}\n"
            )
        else:
            string_to_sign = f"Message\n{payload['Message']}\nMessageId\n{payload['MessageId']}\n"
            if "Subject" in payload:
                string_to_sign += f"Subject\n{payload['Subject']}\n"
            string_to_sign += f"Timestamp\n{payload['Timestamp']}\nTopicArn\n{payload['TopicArn']}\nType\n{payload['Type']}\n"

        logger.debug(f"Canonical string built for {message_type}, length: {len(string_to_sign)} characters")

        # Verify the signature
        try:
            logger.debug("Starting cryptographic signature verification")
            signing_cert.public_key().verify(
                decoded_signature,
                string_to_sign.encode("UTF-8"),
                padding.PKCS1v15(),
                algorithm=signature_hash,
            )
            logger.info("SNS signature verification successful")
            return True
        except Exception as e:
            logger.error(f"SNS signature cryptographic verification failed: {type(e).__name__}: {str(e)}")
            logger.error(f"Exception details: {repr(e)}")
            return False

    except Exception as e:
        logger.error(f"Error during SNS signature verification: {str(e)}", exc_info=True)
        return False


async def verify_azure_webhook(payload: dict, expected_subscription_id: str, expected_action_group_name: str, expected_tenant_id: str = None) -> bool:
    """
    Verify Azure webhook payload to ensure authenticity.
    """
    try:
        import json
        from datetime import datetime, timezone

        essentials = payload.get('data', {}).get('essentials', {})
        alert_context = payload.get('data', {}).get('alertContext', {})

        # Verify subscription ID from alert ID
        alert_id = essentials.get('alertId', '')
        if '/subscriptions/' in alert_id:
            subscription_id = alert_id.split('/subscriptions/')[1].split('/')[0]
            logger.debug(f"Extracted subscription ID from alert ID: {subscription_id}")

            if subscription_id == '11111111-1111-1111-1111-111111111111':
                logger.info("Test alert detected (dummy subscription ID) - skipping all validation")
                return True

            if subscription_id != expected_subscription_id:
                logger.error(f"Subscription ID mismatch: expected {expected_subscription_id}, got {subscription_id}")
                return False

            logger.info("Subscription ID verification passed")
        else:
            logger.error(f"Could not extract subscription ID from alert ID: {alert_id}")
            return False

        tenant_id = alert_context.get('tenantId')
        if tenant_id:
            logger.debug(f"Found tenant ID in alertContext: {tenant_id}")
            if expected_tenant_id and tenant_id != expected_tenant_id:
                logger.error(f"Tenant ID mismatch: expected {expected_tenant_id}, got {tenant_id}")
                return False
            logger.info("Tenant ID verification passed")
        elif expected_tenant_id:
            logger.warning(f"Metric alert detected - no tenant ID in payload to verify (expected: {expected_tenant_id})")
            logger.info("Skipping tenant ID verification for metric alert (relying on subscription ID)")

        signal_type = essentials.get('signalType', '')
        logger.debug(f"Alert signal type: {signal_type}")

        configuration_items = essentials.get('configurationItems', [])

        if signal_type == 'Activity Log':
            if expected_action_group_name not in configuration_items:
                logger.error(f"Action Group name mismatch in Activity Log alert: expected {expected_action_group_name} in {configuration_items}")
                return False
            logger.info("Action Group name verification passed (Activity Log)")
        else:
            logger.debug(f"Metric/Log alert - configurationItems contains resources {configuration_items}, not action group")
            logger.info("Skipping Action Group name verification for Metric/Log alert (not in payload)")

        claims_str = alert_context.get('claims')
        if claims_str:
            logger.info("Activity Log alert with claims detected - performing JWT verification")
            try:
                claims_dict = json.loads(claims_str)
            except json.JSONDecodeError:
                logger.error("Failed to parse Azure claims JSON")
                return False

            exp = claims_dict.get('exp')
            if exp:
                exp_datetime = datetime.fromtimestamp(exp, tz=timezone.utc)
                now = datetime.now(timezone.utc)
                if now >= exp_datetime:
                    logger.error(f"JWT token expired: {exp_datetime} < {now}")
                    return False
                logger.info(f"JWT token expiration check passed (expires: {exp_datetime})")

            iat = claims_dict.get('iat')
            if iat:
                iat_datetime = datetime.fromtimestamp(iat, tz=timezone.utc)
                now = datetime.now(timezone.utc)
                age_seconds = (now - iat_datetime).total_seconds()
                if age_seconds > 300:
                    logger.error(f"JWT token too old: issued {age_seconds} seconds ago")
                    return False
                logger.info(f"JWT token age check passed (issued {age_seconds} seconds ago)")
        else:
            logger.info("Metric/Log alert detected (no claims field) - skipping JWT verification")

        logger.info("Azure webhook verification successful")
        return True

    except Exception as e:
        logger.error(f"Error during Azure webhook verification: {type(e).__name__}: {str(e)}", exc_info=True)
        return False


# ---- Webhook endpoint ----

@router.post("/api/v1/webhooks/cloud_alerts/{project_name}/{cloud_platform}/{account_id}")
async def receive_cloud_alert_webhook(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    request: Request,
    webhook_auth: dict = Depends(authenticate_webhook),
):
    """
    Webhook endpoint for cloud providers to send alerts.
    """
    try:
        import json as json_mod

        # Parse body as JSON
        alert_data = await request.json()
        logger.debug(f"Received webhook payload for {cloud_platform}: {alert_data}")

        # AWS SNS: Verify message signature for security
        if cloud_platform.lower() == 'aws' and alert_data.get('Type') in ['SubscriptionConfirmation', 'Notification', 'UnsubscribeConfirmation']:
            if not await verify_sns_signature(alert_data):
                logger.error("SNS signature verification failed")
                raise HTTPException(status_code=403, detail="Invalid SNS signature")
            logger.debug("SNS signature verified successfully")

            # Verify TopicArn matches our stored topic
            alert_config = AlertConfigurator(project_manager, db_manager)
            config = await alert_config.get_configuration(project_name, cloud_platform, account_id)

            if config and config.get('configured'):
                expected_topic_arn = config.get('cloud_resources', {}).get('topic_arn')
                received_topic_arn = alert_data.get('TopicArn')

                if expected_topic_arn:
                    if received_topic_arn != expected_topic_arn:
                        logger.error(f"TopicArn mismatch: expected {expected_topic_arn}, got {received_topic_arn}")
                        raise HTTPException(status_code=403, detail="TopicArn mismatch - possible spoofing attempt")
                    logger.debug("TopicArn verification passed")
                else:
                    logger.warning("AWS alert configuration missing topic_arn - skipping TopicArn verification")
            else:
                logger.warning("No AWS alert configuration found - skipping TopicArn verification")

        # Azure: Verify JWT and validate tenant/subscription/action group
        if cloud_platform.lower() == 'azure' and alert_data.get('schemaId') == 'azureMonitorCommonAlertSchema':
            alert_config = AlertConfigurator(project_manager, db_manager)
            config = await alert_config.get_configuration(project_name, cloud_platform, account_id)

            if config and config.get('configured'):
                expected_tenant_id = config.get('tenant_id')
                expected_subscription_id = account_id
                expected_action_group_name = config.get('cloud_resources', {}).get('action_group_name')

                if expected_action_group_name:
                    if not await verify_azure_webhook(alert_data, expected_subscription_id, expected_action_group_name, expected_tenant_id):
                        logger.error("Azure webhook verification failed")
                        raise HTTPException(status_code=403, detail="Azure verification failed")
                    logger.debug("Azure webhook verification successful")
                else:
                    logger.warning("Azure alert configuration missing action_group_name - skipping verification")
            else:
                logger.warning("No Azure alert configuration found - skipping verification")

        # AWS SNS: Handle subscription confirmation
        if alert_data.get('Type') == 'SubscriptionConfirmation':
            subscribe_url = alert_data.get('SubscribeURL')
            if subscribe_url:
                from urllib.parse import urlparse
                parsed_url = urlparse(subscribe_url)
                if not parsed_url.hostname or not parsed_url.hostname.endswith('.amazonaws.com'):
                    logger.error(f"Invalid SubscribeURL domain: {parsed_url.hostname}")
                    raise HTTPException(status_code=400, detail="Invalid SubscribeURL domain")

                logger.info(f"Auto-confirming SNS subscription: {subscribe_url}")
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.get(subscribe_url)
                    if response.status_code == 200:
                        logger.info("SNS subscription confirmed successfully")
                        return {"message": "Subscription confirmed"}
                    else:
                        logger.error(f"Failed to confirm SNS subscription: {response.status_code}")
                        raise HTTPException(status_code=500, detail="Failed to confirm subscription")
            else:
                logger.error("SubscriptionConfirmation message missing SubscribeURL")
                raise HTTPException(status_code=400, detail="Missing SubscribeURL")

        # Normalize alert data based on cloud platform
        if cloud_platform.lower() == 'aws':
            if alert_data.get('Type') == 'Notification':
                message_data = alert_data.get('Message')
                if isinstance(message_data, str):
                    message_data = json_mod.loads(message_data)
                alert_data = message_data

        elif cloud_platform.lower() == 'azure':
            if alert_data.get('schemaId') == 'azureMonitorCommonAlertSchema':
                data = alert_data.get('data', {})
                essentials = data.get('essentials', {})
                alert_context = data.get('alertContext', {})

                alert_rule = essentials.get('alertRule', 'Unknown Alert')
                signal_type = essentials.get('signalType', 'Unknown')

                alert_id_val = essentials.get('alertId', '')
                is_test_alert = False
                if '/subscriptions/' in alert_id_val:
                    subscription_id = alert_id_val.split('/subscriptions/')[1].split('/')[0]
                    is_test_alert = subscription_id == '11111111-1111-1111-1111-111111111111'

                summary_prefix = "Synthetic_Test_" if is_test_alert else ""

                alert_data = {
                    'alert_id': alert_id_val,
                    'alert_rule': alert_rule,
                    'severity': essentials.get('severity'),
                    'signal_type': signal_type,
                    'monitor_condition': essentials.get('monitorCondition', '').lower(),
                    'monitoring_service': essentials.get('monitoringService'),
                    'alert_target_ids': essentials.get('alertTargetIDs', []),
                    'fired_datetime': essentials.get('firedDateTime'),
                    'description': essentials.get('description'),
                    'alert_context': alert_context,
                    'cloud_platform': 'azure',
                    'summary': f'{summary_prefix}"{alert_rule}" ({signal_type})'
                }

        elif cloud_platform.lower() == 'gcp':
            if 'incident' in alert_data:
                incident = alert_data.get('incident', {})
                alert_data = {
                    'incident_id': incident.get('incident_id'),
                    'scoping_project_id': incident.get('scoping_project_id'),
                    'url': incident.get('url'),
                    'severity': incident.get('severity'),
                    'started_at': incident.get('started_at'),
                    'ended_at': incident.get('ended_at'),
                    'state': incident.get('state', '').lower(),
                    'resource_id': incident.get('resource_id'),
                    'resource_name': incident.get('resource_name'),
                    'summary': incident.get('summary', ''),
                    'cloud_platform': 'gcp'
                }

        result = await alerts_manager.create_or_update_alert(
            project_name=project_name,
            cloud_platform=cloud_platform,
            account_id=account_id,
            alert_data=alert_data
        )
        logger.info(f"Webhook alert processed successfully: {result}")
        return result
    except ValueError as e:
        logger.error(f"Invalid webhook alert data: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing webhook alert: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error processing alert")


# ---- Alert CRUD ----

@router.get("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/alerts")
@permissions([])
async def list_alerts(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    status: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """List alerts for a specific cloud account with filtering and pagination"""
    try:
        status_filter = status if status != 'all' else None
        result = await alerts_manager.list_alerts(
            cloud_platform=cloud_platform,
            status=status_filter,
            account_id=account_id,
            project_name=project_name,
            start_time=start_time,
            end_time=end_time,
            page=page,
            page_size=page_size
        )
        logger.debug(f"Found {len(result['alerts'])} alerts for {project_name}/{cloud_platform}/{account_id}")
        return result
    except Exception as e:
        logger.error(f"Error listing alerts: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error listing alerts")


# Alert Configuration Endpoints
@router.post("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/alerts/configure")
@permissions(["project_cloud_account_update"])
async def configure_cloud_alerts(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Auto-configure alert forwarding for this cloud account."""
    try:
        webhook_token = authenticator.create_webhook_token(
            project_name, cloud_platform, account_id
        )

        base_url = get_app_base_url()
        if not base_url:
            raise HTTPException(
                status_code=500,
                detail="App base URL not configured. Set 'app.base_url' in app config or DOMAIN environment variable."
            )

        webhook_url = f"{base_url}/api/v1/webhooks/cloud_alerts/{project_name}/{cloud_platform}/{account_id}"

        result = await _alert_configurator_default.configure_alerts(
            project_name=project_name,
            cloud_platform=cloud_platform,
            account_id=account_id,
            webhook_url=webhook_url,
            webhook_token=webhook_token
        )

        return {
            "message": "Alerts configured successfully",
            "webhook_url": webhook_url,
            "configuration": result
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error configuring alerts: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to configure alerts: {str(e)}")


@router.get("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/alerts/configuration")
@permissions(["project_cloud_account_get"])
async def get_alert_configuration_status(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Get the current alert configuration status for this cloud account."""
    try:
        config = await _alert_configurator_default.get_configuration(
            project_name=project_name,
            cloud_platform=cloud_platform,
            account_id=account_id
        )

        if not config:
            return {
                "configured": False,
                "message": "Alerts are not configured for this account"
            }

        return {
            "configured": config.get('configured', False),
            "configured_at": config.get('configured_at'),
            "status": config.get('status'),
            "cloud_resources": config.get('cloud_resources', {}),
            "instructions": config.get('instructions', '')
        }

    except Exception as e:
        logger.error(f"Error getting alert configuration: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get alert configuration")


@router.post("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/alerts/validate")
@permissions(["project_cloud_account_get"])
async def validate_alert_configuration(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Validate that alert configuration resources still exist in the cloud provider."""
    try:
        result = await _alert_configurator_default.validate_configuration(
            project_name=project_name,
            cloud_platform=cloud_platform,
            account_id=account_id
        )
        return result
    except Exception as e:
        logger.error(f"Error validating alert configuration: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to validate alert configuration")


@router.delete("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/alerts/configure")
@permissions(["project_cloud_account_update"])
async def remove_alert_configuration(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Remove alert configuration for this cloud account."""
    try:
        result = await _alert_configurator_default.remove_configuration(
            project_name=project_name,
            cloud_platform=cloud_platform,
            account_id=account_id
        )

        if result:
            return {"message": "Alert configuration removed successfully"}
        else:
            raise HTTPException(status_code=404, detail="Alert configuration not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing alert configuration: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to remove alert configuration")


# this is not used in UI currently, but could be useful for reporting
# NOTE: must be declared BEFORE {alert_id} routes to avoid path parameter shadowing
@router.get("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/alerts/stats")
@permissions([])
async def get_alert_stats_for_account(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Get alert statistics for a specific cloud account"""
    try:
        stats = await alerts_manager.get_alert_stats(
            project_name=project_name,
            account_id=account_id
        )
        return stats
    except Exception as e:
        logger.error(f"Error getting alert stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error getting alert stats")


@router.get("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/alerts/{alert_id}")
@permissions([])
async def get_alert(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    alert_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Get details of a specific alert"""
    try:
        result = await alerts_manager.get_alert_history(alert_id)
        if not result:
            raise HTTPException(status_code=404, detail="Alert not found")

        if (result["project_name"] != project_name or
            result["account_id"] != account_id or
            result["cloud_platform"] != cloud_platform.lower()):
            raise HTTPException(status_code=404, detail="Alert not found")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching alert: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error fetching alert")


@router.put("/api/v1/projects/{project_name}/cloud_accounts/{cloud_platform}/{account_id}/alerts/{alert_id}/resolve")
@permissions([])
async def resolve_alert(
    project_name: str,
    cloud_platform: str,
    account_id: str,
    alert_id: str,
    resolution_data: Models.ResolveAlert,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    """Mark an alert as resolved with a resolution note"""
    try:
        alert = await alerts_manager.get_alert_history(alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")

        if (alert["project_name"] != project_name or
            alert["account_id"] != account_id or
            alert["cloud_platform"] != cloud_platform.lower()):
            raise HTTPException(status_code=404, detail="Alert not found")

        if alert["status"] != "open":
            raise HTTPException(status_code=400, detail="Alert is not in open state")

        result = await alerts_manager.resolve_alert(
            project_name=project_name,
            account_id=account_id,
            cloud_alert_id=alert_id,
            resolved_by=resolution_data.resolved_by,
            resolution_note=resolution_data.resolution_note
        )

        if not result:
            raise HTTPException(status_code=400, detail="Failed to resolve alert")

        return {"message": "Alert resolved successfully"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error resolving alert: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error resolving alert")
