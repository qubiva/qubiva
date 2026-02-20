import os
import tempfile
import base64
from google.oauth2 import service_account
from googleapiclient.discovery import build


class GcpAuthentication:
    def __init__(self, auth_details, auth_type):
        self.auth_details = auth_details
        self.auth_type = auth_type
        self.credentials = None

    async def initialize(self):
        if self.auth_type == 'gcp_service_account':
            credentials_json = self.auth_details.get('google_application_credentials', None)

            if credentials_json:
                try:
                    # Write the JSON content to a temporary file
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
                    temp_file.write(credentials_json.encode('utf-8'))
                    temp_file.close()

                    # Set the path of the temporary file to GOOGLE_APPLICATION_CREDENTIALS
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = temp_file.name
                    print(f"Credentials written to temporary file: {temp_file.name}")
                except Exception as e:
                    raise ValueError(f"Failed to process GOOGLE_APPLICATION_CREDENTIALS: {str(e)}")
            else:
                raise ValueError("No valid GCP credentials provided. The google_application_credentials field is missing or empty.")

            # Initialize the credentials
            self.credentials = service_account.Credentials.from_service_account_file(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
            print("GCP service account initialized successfully.")
        else:
            raise ValueError(f"Unsupported authentication type for GCP: {self.auth_type}")

    async def get_credentials(self):
        return self.credentials

    async def get_session(self):
        return await self.get_credentials()

    async def get_auth_env_vars(self):
        # Base64-encode the original JSON content
        credentials_json = self.auth_details.get('google_application_credentials', None)
        if not credentials_json:
            raise ValueError("google_application_credentials is missing; cannot generate auth environment variables.")

        encoded_credentials = base64.b64encode(credentials_json.encode('utf-8')).decode('utf-8')

        return {
            "GOOGLE_APPLICATION_CREDENTIALS_B64": encoded_credentials
        }

    async def get_client(self, service_name: str, version: str = 'v1'):
        credentials = await self.get_credentials()
        return build(service_name, version, credentials=credentials)
