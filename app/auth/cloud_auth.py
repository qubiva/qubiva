import logging
from app.auth.aws_authentication import AwsAuthentication
from app.auth.gcp_authentication import GcpAuthentication
from app.auth.azure_authentication import AzureAuthentication

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class MultiCloudAuthentication:
    def __init__(self, cloud_platform: str, project_manager, project_name: str, account_id: str):
        logger.info(f"Initializing MultiCloudAuthentication for platform: {cloud_platform}")
        self.cloud_platform = cloud_platform.lower()
        self.project_manager = project_manager
        self.project_name = project_name
        self.account_id = account_id
        self.auth_instance = None

    async def initialize(self):
        logger.info(f"Initializing for platform: {self.cloud_platform}")
        try:
            # Fetch auth details using the project_manager
            auth_details = await self._fetch_auth_details()
            auth_type = auth_details.get('type')
            logger.debug(f"Fetched auth type: {auth_type}")

            # Delegate to the specific cloud platform subclass
            if self.cloud_platform == 'aws':
                logger.debug("Setting up AWS authentication instance")
                self.auth_instance = AwsAuthentication(auth_details, auth_type)
            elif self.cloud_platform == 'gcp':
                logger.debug("Setting up GCP authentication instance")
                self.auth_instance = GcpAuthentication(auth_details, auth_type)
            elif self.cloud_platform == 'azure':
                logger.debug("Setting up Azure authentication instance")
                # For Azure, account_id IS the subscription_id
                self.auth_instance = AzureAuthentication(auth_details, auth_type, subscription_id=self.account_id)
            else:
                logger.error(f"Unsupported cloud platform: {self.cloud_platform}")
                raise ValueError(f"Unsupported cloud platform: {self.cloud_platform}")

            # Initialize the specific authentication instance
            logger.debug("Initializing the auth_instance")
            await self.auth_instance.initialize()
            logger.debug("Auth instance initialized successfully")

        except Exception as e:
            logger.error(f"Error during initialization: {str(e)}", exc_info=True)
            raise

    async def _fetch_auth_details(self):
        logger.info("Fetching auth details from project_manager")
        try:
            success, result = await self.project_manager.get_cloud_account_details(
                self.project_name, self.cloud_platform, self.account_id
            )
            if not success:
                logger.error(f"Failed to fetch cloud account details: {result}")
                raise Exception(f"Failed to fetch cloud account details: {result}")
            logger.info("Auth details fetched successfully")
            return result.get('auth_secrets', {})

        except Exception as e:
            logger.error(f"Error fetching auth details: {str(e)}", exc_info=True)
            raise

    async def get_credentials(self):
        if not self.auth_instance:
            logger.error("auth_instance is None. Did you forget to call initialize()?")  # Debugging line
            raise RuntimeError("auth_instance is not initialized")
        return await self.auth_instance.get_credentials()

    async def get_session(self, region_name: str = None):
        if not self.auth_instance:
            logger.error("auth_instance is None. Did you forget to call initialize()?")  # Debugging line
            raise RuntimeError("auth_instance is not initialized")
        return await self.auth_instance.get_session(region_name)

    async def get_auth_env_vars(self):
        if not self.auth_instance:
            logger.error("auth_instance is None. Did you forget to call initialize()?")
            raise RuntimeError("auth_instance is not initialized")

        # Get credentials from the cloud-specific class
        credentials = await self.get_credentials()

        # First get platform-specific env vars
        if self.cloud_platform.lower() == 'aws':
            env_vars = {
                "AWS_ACCESS_KEY_ID": credentials['accessKeyId'],
                "AWS_SECRET_ACCESS_KEY": credentials['secretAccessKey'],
                "AWS_DEFAULT_REGION": self.auth_instance.region
            }
            if 'sessionToken' in credentials:
                env_vars["AWS_SESSION_TOKEN"] = credentials['sessionToken']

        elif self.cloud_platform.lower() == 'gcp':
            env_vars = await self.auth_instance.get_auth_env_vars()

        elif self.cloud_platform.lower() == 'azure':
            env_vars = {
                "ARM_CLIENT_ID": credentials['client_id'],
                "ARM_CLIENT_SECRET": credentials['client_secret'],
                "ARM_TENANT_ID": credentials['tenant_id']
            }

        # Add CLOUD_PLATFORM to env vars
        env_vars["CLOUD_PLATFORM"] = self.cloud_platform.lower()
        env_vars['CLOUD_ACCOUNT_ID'] = self.account_id

        return env_vars

    async def get_client(self, service_name: str, region_name: str = None):
        if not self.auth_instance:
            logger.error("auth_instance is None. Did you forget to call initialize()?")  # Debugging line
            raise RuntimeError("auth_instance is not initialized")
        return await self.auth_instance.get_client(service_name, region_name)
