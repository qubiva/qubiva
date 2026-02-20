import logging
from typing import Dict, Optional
from datetime import datetime
from urllib.parse import urlparse
from app.auth.cloud_auth import MultiCloudAuthentication

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class AlertConfigurator:
    """
    Handles auto-configuration of alert forwarding for cloud accounts.

    This class:
    - Uses stored cloud credentials to programmatically configure alerts
    - Creates SNS topics (AWS), Action Groups (Azure), Notification Channels (GCP)
    - Configures webhooks to send alerts to Qubiva
    - Stores configuration details for future reference
    """

    def __init__(self, project_manager, db_manager):
        self.project_manager = project_manager
        self.db_manager = db_manager

    async def configure_alerts(
        self,
        project_name: str,
        cloud_platform: str,
        account_id: str,
        webhook_url: str,
        webhook_token: str
    ) -> Dict:
        """
        Auto-configure alert forwarding for a cloud account.

        Args:
            project_name: The project name
            cloud_platform: aws, azure, or gcp
            account_id: The cloud account ID
            webhook_url: The webhook endpoint URL
            webhook_token: The JWT token for webhook authentication

        Returns:
            Dictionary with configuration details and status
        """
        logger.info(f"Configuring alerts for {project_name}/{cloud_platform}/{account_id}")

        # Initialize cloud authentication
        cloudauth = MultiCloudAuthentication(
            cloud_platform=cloud_platform,
            project_manager=self.project_manager,
            project_name=project_name,
            account_id=account_id,
        )
        await cloudauth.initialize()

        # Configure based on cloud platform
        if cloud_platform.lower() == 'aws':
            result = await self._configure_aws_alerts(cloudauth, webhook_url, webhook_token, account_id)
        elif cloud_platform.lower() == 'azure':
            result = await self._configure_azure_alerts(cloudauth, webhook_url, webhook_token, account_id)
        elif cloud_platform.lower() == 'gcp':
            result = await self._configure_gcp_alerts(cloudauth, webhook_url, webhook_token, account_id)
        else:
            raise ValueError(f"Unsupported cloud platform: {cloud_platform}")

        # Store configuration in database
        await self._store_configuration(
            project_name, cloud_platform, account_id, webhook_token, result
        )

        logger.info(f"Alert configuration completed for {project_name}/{cloud_platform}/{account_id}")
        return result

    async def _configure_aws_alerts(
        self, cloudauth: MultiCloudAuthentication, webhook_url: str, webhook_token: str, account_id: str
    ) -> Dict:
        """
        Configure AWS CloudWatch alerts to forward to Qubiva via SNS.

        Creates:
        - SNS Topic for CloudWatch alarms
        - HTTP/HTTPS subscription to webhook endpoint (derived from webhook_url scheme)
        """
        logger.info("Configuring AWS alerts")

        try:
            # Get SNS client (default to us-east-1, can be adjusted)
            sns_client = await cloudauth.get_client('sns', region_name='us-east-1')

            # Create SNS topic with a descriptive name
            topic_name = f'qubiva-alerts-{account_id}'
            logger.debug(f"Creating SNS topic: {topic_name}")

            topic_response = sns_client.create_topic(Name=topic_name)
            topic_arn = topic_response['TopicArn']
            logger.info(f"SNS topic created: {topic_arn}")

            # Derive protocol from the webhook URL scheme
            sns_protocol = urlparse(webhook_url).scheme  # 'http' or 'https'

            # Check for existing subscriptions to this topic with our webhook endpoint
            webhook_url_with_token = f"{webhook_url}?token={webhook_token}"

            # List all subscriptions for this topic
            existing_subscriptions = []
            try:
                paginator = sns_client.get_paginator('list_subscriptions_by_topic')
                for page in paginator.paginate(TopicArn=topic_arn):
                    for sub in page.get('Subscriptions', []):
                        # Check if subscription endpoint matches our webhook (ignoring token differences)
                        if sub['Protocol'] in ('http', 'https') and webhook_url in sub['Endpoint']:
                            existing_subscriptions.append(sub)
            except Exception as e:
                logger.warning(f"Could not list existing subscriptions: {str(e)}")

            # Delete old subscriptions to prevent duplicates
            for old_sub in existing_subscriptions:
                try:
                    if old_sub['SubscriptionArn'] != 'PendingConfirmation':
                        logger.info(f"Deleting old subscription: {old_sub['SubscriptionArn']}")
                        sns_client.unsubscribe(SubscriptionArn=old_sub['SubscriptionArn'])
                except Exception as e:
                    logger.warning(f"Could not delete old subscription: {str(e)}")

            # Subscribe webhook to topic with token in URL (SNS can't send custom headers)
            logger.debug(f"Subscribing webhook to topic: {webhook_url_with_token}")
            subscription_response = sns_client.subscribe(
                TopicArn=topic_arn,
                Protocol=sns_protocol,
                Endpoint=webhook_url_with_token,
                Attributes={
                    'RawMessageDelivery': 'false',  # Get full SNS message wrapper
                },
                ReturnSubscriptionArn=True
            )
            subscription_arn = subscription_response['SubscriptionArn']
            logger.info(f"Webhook subscribed: {subscription_arn}")

            return {
                'status': 'configured',
                'cloud_platform': 'aws',
                'resources': {
                    'topic_arn': topic_arn,
                    'topic_name': topic_name,
                    'subscription_arn': subscription_arn,
                    'region': 'us-east-1'
                },
                'instructions': (
                    f"SNS topic '{topic_name}' has been created. "
                    f"Configure your CloudWatch alarms to send notifications to: {topic_arn}"
                )
            }

        except Exception as e:
            logger.error(f"Failed to configure AWS alerts: {str(e)}", exc_info=True)
            raise Exception(f"AWS alert configuration failed: {str(e)}")

    async def _configure_azure_alerts(
        self, cloudauth: MultiCloudAuthentication, webhook_url: str, webhook_token: str, account_id: str
    ) -> Dict:
        """
        Configure Azure Monitor alerts to forward to Qubiva via Action Groups.

        Creates:
        - Action Group with webhook receiver
        - Webhook configured with token in URL (Azure webhooks don't support custom headers reliably)
        """
        logger.info("Configuring Azure alerts")

        try:
            from azure.mgmt.monitor import MonitorManagementClient
            from azure.mgmt.monitor.models import (
                ActionGroupResource,
                WebhookReceiver
            )
            from azure.identity import ClientSecretCredential
            from azure.mgmt.resource import ResourceManagementClient

            # Get Azure credentials
            credentials_dict = await cloudauth.get_credentials()

            # For Azure, the account_id IS the subscription_id
            subscription_id = account_id

            if not subscription_id:
                raise ValueError("Azure subscription_id is missing")

            # Create credential object
            credential = ClientSecretCredential(
                tenant_id=credentials_dict['tenant_id'],
                client_id=credentials_dict['client_id'],
                client_secret=credentials_dict['client_secret']
            )

            # Initialize clients
            monitor_client = MonitorManagementClient(credential, subscription_id)
            resource_client = ResourceManagementClient(credential, subscription_id)

            # Find an existing resource group to use
            resource_group_name = None
            try:
                resource_groups = list(resource_client.resource_groups.list())
                if resource_groups:
                    # Use the first available resource group
                    resource_group_name = resource_groups[0].name
                    logger.info(f"Using existing resource group: {resource_group_name}")
                else:
                    # No resource groups exist, create one
                    resource_group_name = 'qubiva-monitoring'
                    resource_client.resource_groups.create_or_update(
                        resource_group_name,
                        {'location': 'eastus'}
                    )
                    logger.info(f"Created new resource group: {resource_group_name}")
            except Exception as e:
                logger.error(f"Error finding/creating resource group: {e}")
                # Fallback to default name
                resource_group_name = 'qubiva-monitoring'

            # Generate action group name
            action_group_name = f'qubiva-alerts-{account_id[:8]}'

            # Check for existing action groups with our webhook and delete them
            webhook_url_with_token = f"{webhook_url}?token={webhook_token}"
            try:
                existing_action_groups = list(monitor_client.action_groups.list_by_subscription_id())
                for ag in existing_action_groups:
                    # Check if this action group has our webhook endpoint
                    if ag.webhook_receivers:
                        for receiver in ag.webhook_receivers:
                            if webhook_url in receiver.service_uri:
                                # Extract resource group from action group ID
                                # ID format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Insights/actionGroups/{name}
                                id_parts = ag.id.split('/')
                                ag_resource_group = id_parts[4]
                                ag_name = id_parts[-1]

                                logger.info(f"Deleting old action group: {ag_name}")
                                try:
                                    monitor_client.action_groups.delete(
                                        resource_group_name=ag_resource_group,
                                        action_group_name=ag_name
                                    )
                                except Exception as e:
                                    logger.warning(f"Could not delete old action group: {e}")
            except Exception as e:
                logger.warning(f"Could not list existing action groups: {e}")

            # Create webhook receiver
            webhook_receiver = WebhookReceiver(
                name='qubiva-webhook',
                service_uri=webhook_url_with_token,
                use_common_alert_schema=True  # Use common schema for consistency
            )

            # Create Action Group
            action_group_properties = ActionGroupResource(
                location='Global',  # Action Groups are global resources
                group_short_name='qubiva',  # Max 12 chars
                enabled=True,
                webhook_receivers=[webhook_receiver]
            )

            logger.debug(f"Creating Action Group: {action_group_name}")
            action_group = monitor_client.action_groups.create_or_update(
                resource_group_name=resource_group_name,
                action_group_name=action_group_name,
                action_group=action_group_properties
            )

            action_group_id = action_group.id
            logger.info(f"Azure Action Group created: {action_group_id}")

            return {
                'status': 'configured',
                'cloud_platform': 'azure',
                'resources': {
                    'action_group_id': action_group_id,
                    'action_group_name': action_group_name,
                    'resource_group': resource_group_name,
                    'subscription_id': subscription_id
                },
                'tenant_id': credentials_dict['tenant_id'],  # Store for JWT verification
                'instructions': (
                    f"Azure Action Group '{action_group_name}' has been created. "
                    f"Configure your Azure Monitor alert rules to send notifications to this Action Group. "
                    f"Action Group ID: {action_group_id}"
                )
            }

        except Exception as e:
            logger.error(f"Failed to configure Azure alerts: {str(e)}", exc_info=True)
            raise Exception(f"Azure alert configuration failed: {str(e)}")

    async def _configure_gcp_alerts(
        self, cloudauth: MultiCloudAuthentication, webhook_url: str, webhook_token: str, account_id: str
    ) -> Dict:
        """
        Configure GCP Cloud Monitoring alerts to forward to Qubiva.

        Creates:
        - Notification Channel (webhook with token authentication)
        - Configured to send alerts to Qubiva with token in URL
        """
        logger.info("Configuring GCP alerts")

        try:
            from google.cloud import monitoring_v3

            # Get GCP credentials
            credentials = await cloudauth.get_credentials()

            # Extract project ID from service account JSON
            # The account_id for GCP should be the project_id
            project_id = account_id

            # Initialize Notification Channel Service Client
            client = monitoring_v3.NotificationChannelServiceClient(credentials=credentials)

            # Build project name
            project_name_gcp = f"projects/{project_id}"

            # Include token in webhook URL (GCP webhook_tokenauth expects token in query param)
            webhook_url_with_token = f"{webhook_url}?token={webhook_token}"

            # Create notification channel display name
            display_name = "Qubiva Alerts"

            # Check for existing notification channels with our webhook and delete them
            try:
                existing_channels = client.list_notification_channels(name=project_name_gcp)
                for channel in existing_channels:
                    # Check if this channel is a webhook pointing to our endpoint
                    if channel.type_ == "webhook_tokenauth" and channel.labels.get("url"):
                        if webhook_url in channel.labels["url"]:
                            logger.info(f"Deleting old notification channel: {channel.name}")
                            try:
                                client.delete_notification_channel(name=channel.name)
                            except Exception as e:
                                logger.warning(f"Could not delete old notification channel: {e}")
            except Exception as e:
                logger.warning(f"Could not list existing notification channels: {e}")

            # Create notification channel
            # For webhook_tokenauth, the URL should include the token as a query parameter
            notification_channel = monitoring_v3.NotificationChannel(
                type_="webhook_tokenauth",
                display_name=display_name,
                description="Qubiva alert webhook integration",
                enabled=True,
                labels={
                    "url": webhook_url_with_token
                }
            )

            logger.debug(f"Creating GCP Notification Channel: {display_name}")
            created_channel = client.create_notification_channel(
                name=project_name_gcp,
                notification_channel=notification_channel
            )

            channel_id = created_channel.name
            logger.info(f"GCP Notification Channel created: {channel_id}")

            return {
                'status': 'configured',
                'cloud_platform': 'gcp',
                'resources': {
                    'channel_id': channel_id,
                    'channel_name': display_name,
                    'project_id': project_id
                },
                'instructions': (
                    f"GCP Notification Channel '{display_name}' has been created. "
                    f"Configure your Cloud Monitoring alert policies to send notifications to this channel. "
                    f"Channel ID: {channel_id}"
                )
            }

        except Exception as e:
            logger.error(f"Failed to configure GCP alerts: {str(e)}", exc_info=True)
            raise Exception(f"GCP alert configuration failed: {str(e)}")

    async def _store_configuration(
        self,
        project_name: str,
        cloud_platform: str,
        account_id: str,
        webhook_token: str,
        config_result: Dict
    ):
        """Store alert configuration in the database."""
        try:
            await self.db_manager.update_document(
                'cloud_accounts',
                {
                    'project_name': project_name,
                    'cloud_platform': cloud_platform.lower(),
                    'account_id': account_id
                },
                {
                    'alert_configuration': {
                        'configured': True,
                        'configured_at': datetime.utcnow().isoformat(),
                        'webhook_token': webhook_token,
                        'status': config_result.get('status'),
                        'cloud_resources': config_result.get('resources', {}),
                        'instructions': config_result.get('instructions', '')
                    }
                }
            )
            logger.info(f"Alert configuration stored in database for {project_name}/{cloud_platform}/{account_id}")
        except Exception as e:
            logger.error(f"Failed to store alert configuration: {str(e)}")
            raise

    async def get_configuration(
        self, project_name: str, cloud_platform: str, account_id: str
    ) -> Optional[Dict]:
        """Get the current alert configuration for a cloud account."""
        try:
            account = await self.db_manager.find_document(
                'cloud_accounts',
                {
                    'project_name': project_name,
                    'cloud_platform': cloud_platform.lower(),
                    'account_id': account_id
                }
            )
            if account:
                return account.get('alert_configuration')
            return None
        except Exception as e:
            logger.error(f"Failed to get alert configuration: {str(e)}")
            raise

    async def validate_configuration(
        self, project_name: str, cloud_platform: str, account_id: str
    ) -> Dict:
        """
        Validate that alert configuration resources still exist in the cloud provider.
        If resources are missing, marks configuration as invalid in database.
        """
        try:
            # Get current configuration
            config = await self.get_configuration(project_name, cloud_platform, account_id)

            if not config or not config.get('configured'):
                return {
                    "valid": False,
                    "message": "No alert configuration found"
                }

            cloud_resources = config.get('cloud_resources', {})

            # Validate based on cloud platform
            if cloud_platform.lower() == 'aws':
                topic_arn = cloud_resources.get('topic_arn')
                if not topic_arn:
                    return {"valid": False, "message": "Missing topic ARN in configuration"}

                # Get cloud credentials
                cloudauth = MultiCloudAuthentication(
                    cloud_platform=cloud_platform,
                    project_manager=self.project_manager,
                    project_name=project_name,
                    account_id=account_id,
                )
                await cloudauth.initialize()

                # Check if SNS topic exists
                sns_client = await cloudauth.get_client('sns', region_name='us-east-1')
                try:
                    sns_client.get_topic_attributes(TopicArn=topic_arn)
                    return {
                        "valid": True,
                        "message": "Alert configuration is valid",
                        "resources": cloud_resources
                    }
                except sns_client.exceptions.NotFoundException:
                    # Topic doesn't exist, mark as invalid
                    await self.db_manager.update_document(
                        'cloud_accounts',
                        {
                            'project_name': project_name,
                            'cloud_platform': cloud_platform.lower(),
                            'account_id': account_id
                        },
                        {
                            'alert_configuration.status': 'invalid',
                            'alert_configuration.configured': False
                        }
                    )
                    return {
                        "valid": False,
                        "message": "SNS topic no longer exists. Configuration marked as invalid."
                    }

            elif cloud_platform.lower() == 'azure':
                action_group_id = cloud_resources.get('action_group_id')
                if not action_group_id:
                    return {"valid": False, "message": "Missing action group ID in configuration"}

                # Get cloud credentials
                cloudauth = MultiCloudAuthentication(
                    cloud_platform=cloud_platform,
                    project_manager=self.project_manager,
                    project_name=project_name,
                    account_id=account_id,
                )
                await cloudauth.initialize()

                # Check if Action Group exists
                try:
                    from azure.mgmt.monitor import MonitorManagementClient
                    from azure.identity import ClientSecretCredential

                    credentials_dict = await cloudauth.get_credentials()
                    credential = ClientSecretCredential(
                        tenant_id=credentials_dict['tenant_id'],
                        client_id=credentials_dict['client_id'],
                        client_secret=credentials_dict['client_secret']
                    )

                    # Parse resource group and action group name from ID
                    # ID format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Insights/actionGroups/{name}
                    id_parts = action_group_id.split('/')
                    resource_group = id_parts[4]
                    action_group_name = id_parts[-1]
                    subscription_id = id_parts[2]

                    monitor_client = MonitorManagementClient(credential, subscription_id)
                    monitor_client.action_groups.get(resource_group, action_group_name)

                    return {
                        "valid": True,
                        "message": "Alert configuration is valid",
                        "resources": cloud_resources
                    }
                except Exception as e:
                    # Action Group doesn't exist, mark as invalid
                    await self.db_manager.update_document(
                        'cloud_accounts',
                        {
                            'project_name': project_name,
                            'cloud_platform': cloud_platform.lower(),
                            'account_id': account_id
                        },
                        {
                            'alert_configuration.status': 'invalid',
                            'alert_configuration.configured': False
                        }
                    )
                    return {
                        "valid": False,
                        "message": f"Action Group no longer exists: {str(e)}. Configuration marked as invalid."
                    }

            elif cloud_platform.lower() == 'gcp':
                channel_id = cloud_resources.get('channel_id')
                if not channel_id:
                    return {"valid": False, "message": "Missing notification channel ID in configuration"}

                # Get cloud credentials
                cloudauth = MultiCloudAuthentication(
                    cloud_platform=cloud_platform,
                    project_manager=self.project_manager,
                    project_name=project_name,
                    account_id=account_id,
                )
                await cloudauth.initialize()

                # Check if Notification Channel exists
                try:
                    from google.cloud import monitoring_v3

                    credentials = await cloudauth.get_credentials()
                    client = monitoring_v3.NotificationChannelServiceClient(credentials=credentials)

                    client.get_notification_channel(name=channel_id)

                    return {
                        "valid": True,
                        "message": "Alert configuration is valid",
                        "resources": cloud_resources
                    }
                except Exception as e:
                    # Notification Channel doesn't exist, mark as invalid
                    await self.db_manager.update_document(
                        'cloud_accounts',
                        {
                            'project_name': project_name,
                            'cloud_platform': cloud_platform.lower(),
                            'account_id': account_id
                        },
                        {
                            'alert_configuration.status': 'invalid',
                            'alert_configuration.configured': False
                        }
                    )
                    return {
                        "valid": False,
                        "message": f"Notification Channel no longer exists: {str(e)}. Configuration marked as invalid."
                    }

            else:
                return {"valid": False, "message": f"Unsupported platform: {cloud_platform}"}

        except Exception as e:
            logger.error(f"Failed to validate alert configuration: {str(e)}", exc_info=True)
            return {
                "valid": False,
                "message": f"Validation failed: {str(e)}"
            }

    async def remove_configuration(
        self, project_name: str, cloud_platform: str, account_id: str
    ) -> bool:
        """
        Remove alert configuration and clean up cloud resources.
        """
        try:
            # Get current configuration to find cloud resources to delete
            config = await self.get_configuration(project_name, cloud_platform, account_id)

            if config and config.get('configured'):
                cloud_resources = config.get('cloud_resources', {})

                # Initialize cloud authentication
                cloudauth = MultiCloudAuthentication(
                    cloud_platform=cloud_platform,
                    project_manager=self.project_manager,
                    project_name=project_name,
                    account_id=account_id,
                )
                await cloudauth.initialize()

                # Delete cloud resources based on platform
                if cloud_platform.lower() == 'aws':
                    topic_arn = cloud_resources.get('topic_arn')
                    if topic_arn:
                        try:
                            sns_client = await cloudauth.get_client('sns', region_name='us-east-1')

                            # Delete all subscriptions first
                            subscriptions = sns_client.list_subscriptions_by_topic(TopicArn=topic_arn)
                            for subscription in subscriptions.get('Subscriptions', []):
                                sns_client.unsubscribe(SubscriptionArn=subscription['SubscriptionArn'])
                                logger.info(f"Deleted SNS subscription: {subscription['SubscriptionArn']}")

                            # Delete the topic
                            sns_client.delete_topic(TopicArn=topic_arn)
                            logger.info(f"Deleted SNS topic: {topic_arn}")
                        except Exception as e:
                            logger.warning(f"Failed to delete AWS SNS topic: {str(e)}")

                elif cloud_platform.lower() == 'azure':
                    action_group_id = cloud_resources.get('action_group_id')
                    if action_group_id:
                        try:
                            from azure.mgmt.monitor import MonitorManagementClient
                            from azure.identity import ClientSecretCredential

                            credentials_dict = await cloudauth.get_credentials()
                            credential = ClientSecretCredential(
                                tenant_id=credentials_dict['tenant_id'],
                                client_id=credentials_dict['client_id'],
                                client_secret=credentials_dict['client_secret']
                            )

                            # Parse resource group and action group name from ID
                            # ID format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Insights/actionGroups/{name}
                            id_parts = action_group_id.split('/')
                            resource_group = id_parts[4]
                            action_group_name = id_parts[-1]
                            subscription_id = id_parts[2]

                            monitor_client = MonitorManagementClient(credential, subscription_id)
                            monitor_client.action_groups.delete(resource_group, action_group_name)
                            logger.info(f"Deleted Azure Action Group: {action_group_id}")
                        except Exception as e:
                            logger.warning(f"Failed to delete Azure Action Group: {str(e)}")

                elif cloud_platform.lower() == 'gcp':
                    channel_id = cloud_resources.get('channel_id')
                    if channel_id:
                        try:
                            from google.cloud import monitoring_v3

                            credentials = await cloudauth.get_credentials()
                            client = monitoring_v3.NotificationChannelServiceClient(credentials=credentials)

                            client.delete_notification_channel(name=channel_id)
                            logger.info(f"Deleted GCP Notification Channel: {channel_id}")
                        except Exception as e:
                            logger.warning(f"Failed to delete GCP Notification Channel: {str(e)}")

            # Remove database configuration
            result = await self.db_manager.update_document(
                'cloud_accounts',
                {
                    'project_name': project_name,
                    'cloud_platform': cloud_platform.lower(),
                    'account_id': account_id
                },
                {
                    'alert_configuration': None
                }
            )
            logger.info(f"Alert configuration removed for {project_name}/{cloud_platform}/{account_id}")
            return result > 0
        except Exception as e:
            logger.error(f"Failed to remove alert configuration: {str(e)}")
            raise
