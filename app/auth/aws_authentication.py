import datetime
import logging
import base64
import hashlib
import json
import requests
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.hashes import SHA256
import boto3

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class AwsAuthentication:
    def __init__(self, auth_details, auth_type):
        logger.info(f"Initializing AwsAuthentication with auth_type: {auth_type}")
        self.auth_details = auth_details
        self.auth_type = auth_type
        self.region = None
        self._credentials = None
        self._credentials_expiry = None

    async def initialize(self):
        if self.auth_type == 'external_certificate_authority':
            self.region = self._extract_region_from_arn(self.auth_details.get('profile_arn', ''))
        logger.info(f"Initialized with auth_type: {self.auth_type}, region: {self.region}")

    @staticmethod
    def _extract_region_from_arn(arn: str) -> str:
        parts = arn.split(':')
        return parts[3] if len(parts) > 3 else ''

    async def get_credentials(self):
        logger.info("Getting credentials")
        if self._credentials_expired():
            logger.info("Credentials expired or not set, refreshing")
            if self.auth_type == 'external_certificate_authority':
                await self._get_credentials_with_certificate()
            elif self.auth_type == 'key_pair':
                self._get_credentials_with_secret_key()
            else:
                logger.error(f"Unsupported authentication type: {self.auth_type}")
                raise ValueError(f"Unsupported authentication type: {self.auth_type}")
        return self._credentials

    def _credentials_expired(self) -> bool:
        return (self._credentials is None or
                datetime.datetime.now(datetime.timezone.utc) >= self._credentials_expiry)

    async def _get_credentials_with_certificate(self):
        logger.info("Getting credentials with certificate")
        try:
            response = await self._create_signed_request()
            if response is None:
                logger.error("_create_signed_request returned None")
                raise Exception("Failed to create signed request")

            if not response.ok:
                logger.error(f"Request failed with status code: {response.status_code}")
                logger.error(f"Response content: {response.text}")
                raise Exception(f"Request failed with status code: {response.status_code}")

            try:
                response_dict = response.json()
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON response: {str(e)}")
                logger.error(f"Response content: {response.text}")
                raise

            if 'credentialSet' not in response_dict or not response_dict['credentialSet']:
                logger.error(f"Unexpected response format. Response: {response_dict}")
                raise Exception("Unexpected response format")

            credentials = response_dict['credentialSet'][0]['credentials']
            self._credentials = {
                "accessKeyId": credentials['accessKeyId'],
                "secretAccessKey": credentials['secretAccessKey'],
                "sessionToken": credentials['sessionToken']
            }
            self._credentials_expiry = (datetime.datetime.now(datetime.timezone.utc) +
                                        datetime.timedelta(seconds=3600 - 300))
            logger.info("Successfully obtained credentials with certificate")
        except Exception as e:
            logger.error(f"Failed to get credentials with certificate: {str(e)}", exc_info=True)
            raise

    def _get_credentials_with_secret_key(self):
        logger.info("Getting credentials with secret key")
        logger.debug(f"AUTH_DETAILS RECEIVED: {self.auth_details}")

        access_key = self.auth_details.get('access_key_id', '')
        secret_key = self.auth_details.get('secret_access_key', '')

        logger.debug(f"ACCESS_KEY_ID: {access_key[:10]}..." if access_key else "ACCESS_KEY_ID: EMPTY")
        logger.debug(f"SECRET_ACCESS_KEY: {secret_key[:10]}..." if secret_key else "SECRET_ACCESS_KEY: EMPTY")

        self._credentials = {
            "accessKeyId": access_key,
            "secretAccessKey": secret_key
        }
        self._credentials_expiry = (datetime.datetime.now(datetime.timezone.utc) +
                                    datetime.timedelta(days=365))
        logger.info("Successfully obtained credentials with secret key")
        logger.debug(f"FINAL CREDENTIALS: accessKeyId={self._credentials['accessKeyId'][:10]}..., secretAccessKey={self._credentials['secretAccessKey'][:10]}...")

    async def _create_signed_request(self):
        logger.info("Creating signed request")
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            amz_date = now.strftime('%Y%m%dT%H%M%SZ')
            date_stamp = now.strftime('%Y%m%d')
            service = 'rolesanywhere'
            host = f'{service}.{self.region}.amazonaws.com'
            endpoint = f'https://{host}'
            content_type = 'application/json'
            method = 'POST'
            canonical_uri = '/sessions'

            cert_data = self.auth_details.get('certificate', '')
            key_data = self.auth_details.get('key', '')

            if not cert_data or not key_data:
                logger.error("Certificate or key data is missing")
                raise ValueError("Certificate or key data is missing")

            try:
                cert = x509.load_pem_x509_certificate(cert_data.encode('utf-8'))
                private_key = serialization.load_pem_private_key(key_data.encode('utf-8'), password=None)
            except Exception as e:
                logger.error(f"Failed to load certificate or key: {str(e)}")
                raise

            payload = json.dumps({
                "durationSeconds": 3600,
                "profileArn": self.auth_details.get('profile_arn', ''),
                "roleArn": self.auth_details.get('role_arn', ''),
                "sessionName": 'assume_role_session',
                "trustAnchorArn": self.auth_details.get('trust_anchor_arn', '')
            })
            logger.debug(f"Request payload: {payload}")

            payload_hash = hashlib.sha256(payload.encode('utf-8')).hexdigest()
            canonical_headers = (
                f'content-type:{content_type}\n'
                f'host:{host}\n'
                f'x-amz-date:{amz_date}\n'
                f'x-amz-x509:{base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()}'
            )
            signed_headers = 'content-type;host;x-amz-date;x-amz-x509'

            canonical_request = (
                f'{method}\n{canonical_uri}\n\n{canonical_headers}\n\n'
                f'{signed_headers}\n{payload_hash}'
            )
            logger.debug(f"Canonical request: {canonical_request}")

            algorithm = 'AWS4-X509-RSA-SHA256'
            credential_scope = f'{date_stamp}/{self.region}/{service}/aws4_request'
            string_to_sign = (
                f'{algorithm}\n{amz_date}\n{credential_scope}\n'
                f'{hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()}'
            )
            logger.debug(f"String to sign: {string_to_sign}")

            try:
                signature = private_key.sign(
                    data=string_to_sign.encode('utf-8'),
                    padding=padding.PKCS1v15(),
                    algorithm=SHA256()
                )
                signature_hex = signature.hex()
            except Exception as e:
                logger.error(f"Failed to create signature: {str(e)}")
                raise

            authorization_header = (
                f'{algorithm} '
                f'Credential={cert.serial_number}/{credential_scope}, '
                f'SignedHeaders={signed_headers}, '
                f'Signature={signature_hex}'
            )

            headers = {
                'Content-Type': content_type,
                'X-Amz-Date': amz_date,
                'X-Amz-X509': base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode(),
                'Authorization': authorization_header
            }
            logger.debug(f"Request headers: {headers}")

            logger.info(f"Sending request to {endpoint + canonical_uri}")
            response = requests.post(endpoint + canonical_uri, data=payload, headers=headers)
            logger.info(f"Received response with status code: {response.status_code}")

            if not response.ok:
                logger.error(f"Request failed. Status code: {response.status_code}")
                logger.error(f"Response content: {response.text}")
            else:
                logger.info("Request successful")
                logger.debug(f"Response content: {response.text}")

            return response
        except Exception as e:
            logger.error(f"Error in _create_signed_request: {str(e)}", exc_info=True)
            return None

    async def get_session(self, region_name: str = None):
        logger.info(f"Getting AWS session for region: {region_name or self.region}")
        credentials = await self.get_credentials()
        session_params = {
            "aws_access_key_id": credentials['accessKeyId'],
            "aws_secret_access_key": credentials['secretAccessKey'],
            "region_name": region_name or self.region
        }
        if 'sessionToken' in credentials:
            session_params["aws_session_token"] = credentials['sessionToken']

        return boto3.Session(**session_params)

    async def get_client(self, service_name: str, region_name: str = None):
        logger.info(f"Getting AWS client for service: {service_name}, region: {region_name or self.region}")
        session = await self.get_session(region_name)
        return session.client(service_name)
