import bcrypt
import logging
from datetime import datetime

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class UserAuthentication:
    def __init__(self, db_manager, kms_manager):
        self.db_manager = db_manager
        self.kms_manager = kms_manager
        self.user_collection_name = "users"

    def hash_password(self, password: str):
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def verify_password(self, plain_password: str, hashed_password: str):
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

    def create_access_token(self, username: str, expiry_hours=1, renewal_count=0):
        # Using KMS JWT with 1-hour expiry to match current behavior
        # renewal_count tracks how many times this session has been renewed
        return self.kms_manager.create_jwt(
            subject=username,
            expiry_hours=expiry_hours,
            additional_claims={"renewal_count": renewal_count}
        )

    def decode_access_token(self, token: str):
        try:
            payload = self.kms_manager.verify_jwt(token)
            return payload["sub"]  # username
        except Exception as E:
            logger.debug(f"Token decode failed with error: {type(E).__name__} - {str(E)}")
            return None

    def get_token_payload(self, token: str):
        """Get full token payload including exp, iat, renewal_count"""
        try:
            payload = self.kms_manager.verify_jwt(token)
            return payload
        except Exception as E:
            logger.debug(f"Token decode failed with error: {type(E).__name__} - {str(E)}")
            return None

    def create_webhook_token(self, project_name: str, cloud_platform: str,
                            account_id: str, expiry_hours: int = 87600):
        """
        Create a scoped JWT token for cloud webhook endpoints only.

        This token:
        - Can ONLY be used for webhook alert endpoints
        - Is bound to a specific project/platform/account
        - Has a long expiry (default: 10 years = 87600 hours)
        - Cannot be used for any other API endpoints

        Args:
            project_name: The project name
            cloud_platform: aws, azure, or gcp
            account_id: The cloud account ID
            expiry_hours: Token expiry in hours (default: 10 years)

        Returns:
            JWT token string
        """
        return self.kms_manager.create_jwt(
            subject="qubiva-webhook-service",
            expiry_hours=expiry_hours,
            additional_claims={
                "token_type": "webhook",
                "scope": "cloud_alerts_webhook_only",
                "project_name": project_name,
                "cloud_platform": cloud_platform.lower(),
                "account_id": account_id
            }
        )

    # ========== MODIFIED METHOD #1: authenticate_user ==========
    async def authenticate_user(self, username: str, password: str):
        user = await self.db_manager.find_document("users", {"username": username})
        if not user:
            return None

        # CRITICAL: Check if user is deactivated
        if not user.get("active", True):  # Default True for backwards compatibility
            logger.warning(f"Blocked login attempt by deactivated user: {username}")
            return None

        # CRITICAL: SSO users cannot use local password authentication
        if user.get("auth_method") == "sso":
            logger.warning(f"SSO user {username} attempted local password login")
            return None

        # Verify password for local users
        if user.get("hashed_password") and self.verify_password(password, user["hashed_password"]):
            return user

        return None
    # ========== END MODIFIED METHOD #1 ==========

    # async def register_user(self, username: str, password: str):
    #     hashed_password = self.hash_password(password)
    #     user_data = {"username": username, "hashed_password": hashed_password}
    #     return await self.db_manager.insert_document("users", user_data)

    # ========== MODIFIED METHOD #2: get_current_user ==========
    async def get_current_user(self, session_token: str):
        username = self.decode_access_token(session_token)
        if not username:
            return None

        user = await self.db_manager.find_document("users", {"username": username})

        # CRITICAL: Check if user is deactivated
        if user and not user.get("active", True):  # Default True for backwards compatibility
            logger.warning(f"Blocked access by deactivated user: {username}")
            return None

        return user
    # ========== END MODIFIED METHOD #2 ==========

    async def search_users(self, query: str):
        """Search users by username based on a query string."""
        regex_query = {"username": {"$regex": f"^{query}", "$options": "i"}}
        users = await self.db_manager.find_documents("users", regex_query)
        # Exclude the '_id' field in the returned data
        return [{key: user[key] for key in user if key != '_id'} for user in users]

    async def get_all_users(self):
        """Retrieve a list of user objects with 'username' and 'org_roles' fields."""
        users = await self.db_manager.find_all("users")
        # Return a list of user objects containing 'username' and 'org_roles'
        return [{"username": user["username"], "org_roles": user.get("org_roles", [])} for user in users if "username" in user]

    # API Tokens
    async def create_api_token(
        self, username: str, expiry: int, token_name: str = "General", expiry_type: str = "hours"):
        """
        Generate an API token and store it with metadata.

        Returns:
            bool: True if the operation was successful, False otherwise.
            str: Success or error message.
        """
        # Convert expiry to hours if needed
        expiry_hours = expiry * 24 if expiry_type == "days" else expiry

        # Generate the token
        token = self.kms_manager.create_jwt(subject=username, expiry_hours=expiry_hours)

        # Fetch the user document
        user = await self.db_manager.find_document(self.user_collection_name, {"username": username})
        if not user:
            return False, "User not found"

        # Ensure the api_tokens array exists
        api_tokens = user.get("api_tokens", [])

        # Check for duplicate token_name
        if any(t["token_name"] == token_name for t in api_tokens):
            return False, f"Token name '{token_name}' already exists. Please choose a different name."

        # Enforce token limit
        if len(api_tokens) >= 5:
            return False, "Maximum API tokens reached. Revoke existing tokens to create new ones."

        # Add the new token with metadata
        api_tokens.append(
            {
                "token": token,
                "created_at": datetime.utcnow().isoformat(),
                "token_name": token_name,
                "expiry_hours": expiry_hours,
            }
        )

        # Update the user's document (directly pass the updated data)
        update_result = await self.db_manager.update_document(
            self.user_collection_name,
            {"username": username},
            {"api_tokens": api_tokens},
        )

        # Check if the update was successful
        if update_result == 0:
            return False, "Failed to update user with new API token. Please try again."

        return True, token

    async def revoke_api_token(self, username: str, token_name: str):
        """
        Revoke an API token by removing it from the user's document.

        Returns:
            bool: True if the operation was successful, False otherwise.
            str: Success or error message.
        """
        # Fetch the user document
        user = await self.db_manager.find_document(self.user_collection_name, {"username": username})
        if not user:
            return False, "User not found"

        # Ensure the api_tokens array exists
        api_tokens = user.get("api_tokens", [])
        token_revoked = False

        # Find and remove the token based on the token_name
        updated_tokens = []
        for t in api_tokens:
            if t["token_name"] == token_name:
                token_revoked = True
            else:
                updated_tokens.append(t)

        # If token was not found
        if not token_revoked:
            return False, "Token not found or already revoked"

        # Update the user's document
        update_result = await self.db_manager.update_document(
            self.user_collection_name,
            {"username": username},
            {"api_tokens": updated_tokens},
        )

        # Check if the update was successful
        if update_result == 0:
            return False, "Failed to update user document after revoking the token."

        return True, "Token revoked successfully."
