import base64
import os
import json
import logging
from datetime import datetime, timedelta
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
from typing import Dict, Optional, Union
import hashlib
import random
from sympy import isprime

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class KMSManager:
    def __init__(self):
        """
        Initialize encryption manager with local Fernet encryption and RSA JWT signing.
        All keys are derived from environment variables - no cloud provider dependencies.
        """
        # Initialize Fernet encryption
        local_encryption_key = os.getenv("LOCAL_ENCRYPTION_KEY")
        if not local_encryption_key:
            raise ValueError("LOCAL_ENCRYPTION_KEY environment variable must be set")
        try:
            self.local_cipher = Fernet(local_encryption_key.encode("utf-8"))
            logger.info("Encryption initialized with local Fernet key")
        except Exception as e:
            raise ValueError(f"Invalid LOCAL_ENCRYPTION_KEY format: {str(e)}")

        # Initialize RSA JWT signing
        local_signing_key = os.getenv("LOCAL_SIGNING_KEY")
        if not local_signing_key:
            raise ValueError("LOCAL_SIGNING_KEY environment variable must be set")
        try:
            self._init_local_jwt_keys(local_signing_key)
            logger.info("JWT signing initialized with local RSA keys")
        except Exception as e:
            raise ValueError(f"Failed to initialize local JWT signing keys: {str(e)}")

    def _init_local_jwt_keys(self, local_signing_key: str):
        """Initialize local RSA keys for JWT signing using a consistent seed."""
        seed_bytes = hashlib.sha256(local_signing_key.encode()).digest()
        rng = random.Random(int.from_bytes(seed_bytes, 'big'))

        def get_prime(size):
            while True:
                num = rng.getrandbits(size)
                num |= 1
                if isprime(num):
                    return num

        p = get_prime(1024)
        q = get_prime(1024)

        private_numbers = rsa.RSAPrivateNumbers(
            p=p,
            q=q,
            d=pow(65537, -1, (p - 1) * (q - 1)),
            dmp1=pow(65537, -1, p - 1),
            dmq1=pow(65537, -1, q - 1),
            iqmp=pow(q, -1, p),
            public_numbers=rsa.RSAPublicNumbers(
                e=65537,
                n=p * q
            )
        )

        self.local_private_key = private_numbers.private_key(default_backend())
        self.local_public_key = self.local_private_key.public_key()
        logger.debug("Local JWT keys initialized with deterministic generation")

    def encrypt(self, plaintext_data: str) -> str:
        """Encrypt data using local Fernet encryption"""
        try:
            encrypted_data = self.local_cipher.encrypt(plaintext_data.encode("utf-8"))
            return encrypted_data.decode("utf-8")
        except Exception as e:
            logger.error("Encryption failed: %s", e)
            raise

    def decrypt(self, encrypted_data: Union[str, bytes]) -> str:
        """Decrypt data using local Fernet encryption"""
        if isinstance(encrypted_data, bytes):
            encrypted_data = encrypted_data.decode("utf-8")
        try:
            decrypted_data = self.local_cipher.decrypt(encrypted_data.encode("utf-8"))
            return decrypted_data.decode("utf-8")
        except InvalidToken as e:
            logger.error("Decryption failed: %s", e)
            raise

    def create_jwt(self, subject: str, expiry_hours: int = 1,
                  additional_claims: Optional[Dict] = None) -> str:
        """Create and sign a JWT token using local RSA key"""
        header = {
            "alg": "RS256",
            "typ": "JWT",
            "kid": "local-signing-key"
        }

        now = datetime.utcnow()
        payload = {
            "sub": subject,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=expiry_hours)).timestamp()),
            "iss": "qubiva-jwt-issuer"
        }
        if additional_claims:
            payload.update(additional_claims)

        header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b'=').decode()
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=').decode()
        message = f"{header_b64}.{payload_b64}"

        try:
            signature = self.local_private_key.sign(
                message.encode(),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b'=').decode()
            return f"{message}.{signature_b64}"
        except Exception as e:
            logger.error("JWT signing failed: %s", e)
            raise

    def verify_jwt(self, token: str) -> Dict:
        """Verify a JWT token and return its payload"""
        try:
            header_b64, payload_b64, signature_b64 = token.split('.')
            message = f"{header_b64}.{payload_b64}"
            signature = base64.urlsafe_b64decode(signature_b64 + '=' * (-len(signature_b64) % 4))

            try:
                self.local_public_key.verify(
                    signature,
                    message.encode(),
                    padding.PKCS1v15(),
                    hashes.SHA256()
                )
            except Exception as e:
                logger.error("JWT verification failed: %s", e)
                raise ValueError("Invalid JWT signature")

            payload = json.loads(base64.urlsafe_b64decode(
                payload_b64 + '=' * (-len(payload_b64) % 4)
            ))

            if payload["exp"] < datetime.utcnow().timestamp():
                raise ValueError("Token has expired")

            return payload

        except Exception as e:
            logger.error("JWT verification failed: %s", e)
            raise
