import logging
from azure.identity import ClientSecretCredential
from azure.mgmt import resource

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class AzureAuthentication:
    def __init__(self, auth_details, auth_type, subscription_id=None):
        logger.info(f"Initializing AzureAuthentication with auth_type: {auth_type}")
        self.auth_details = auth_details
        self.auth_type = auth_type
        self.credentials = None
        # Store subscription_id separately since it's not in auth_details
        self.subscription_id = subscription_id or self.auth_details.get('subscription_id')

    async def initialize(self):
        if self.auth_type == 'azure_service_principal':
            # Store the raw credentials dictionary instead of the ClientSecretCredential
            self.credentials = {
                'client_id': self.auth_details.get('azure_client_id'),
                'tenant_id': self.auth_details.get('azure_tenant_id'),
                'client_secret': self.auth_details.get('azure_client_secret')
            }

            if not all(self.credentials.values()):
                logger.error("Azure credentials (client_id, tenant_id, client_secret) are not set")
                raise ValueError("Azure credentials (client_id, tenant_id, client_secret) are not set")

            logger.info("Azure service principal credentials initialized successfully")
        else:
            logger.error(f"Unsupported authentication type for Azure: {self.auth_type}")
            raise ValueError(f"Unsupported authentication type for Azure: {self.auth_type}")

    async def get_credentials(self):
        # Return the raw credentials dictionary
        return self.credentials

    async def get_session(self):
        logger.info("Getting Azure session")
        # Create and return the ClientSecretCredential only when needed
        return ClientSecretCredential(
            tenant_id=self.credentials['tenant_id'],
            client_id=self.credentials['client_id'],
            client_secret=self.credentials['client_secret']
        )

    async def get_client(self, service_name: str):
        logger.info(f"Getting Azure client for service: {service_name}")
        credentials = await self.get_session()  # Get ClientSecretCredential here
        try:
            client_module = getattr(resource, service_name)
            return client_module(credentials, self.subscription_id)
        except AttributeError:
            logger.error(f"Unsupported or invalid Azure service: {service_name}")
            raise ValueError(f"Unsupported or invalid Azure service: {service_name}")
