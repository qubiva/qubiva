import logging
import bcrypt
import jwt
import random
import string
import threading
from typing import List, Tuple
from datetime import datetime
from app.managers.base import ManagerBase

logger = logging.getLogger('uvicorn.error')


class UserManager(ManagerBase):
    def __init__(self, db_manager, kms_manager, email_service, rbac):
        super().__init__(db_manager, kms_manager)
        self.email_service = email_service
        self.rbac = rbac

    async def create_users(self, users: List[dict], acting_user: str = None) -> Tuple[bool, str]:
        """
        Creates multiple users with organization roles and sends an email notification.
        """
        logger.debug(f"Received {len(users)} user(s) to create")

        # Validate `users` input
        if not isinstance(users, list):
            logger.error("Invalid input: 'users' is not a list or is None.")
            return False, "'users' must be a list of user dictionaries."

        try:
            org_roles = set(self.rbac.get_all_org_roles())
            usernames = set()
            created_users = []
            existing_users = []  # Track users that already exist

            # Step 1: Validate all users at once
            for user in users:
                username = user.get('username')
                if not username or not isinstance(username, str):
                    logger.error(f"Invalid username provided: {username}")
                    return False, "Invalid username provided. Each user must have a valid email address."

                roles = user.get('org_roles') or []
                if not isinstance(roles, list):
                    logger.error(f"Invalid org_roles for user '{username}': {roles}")
                    return False, f"Invalid roles for user '{username}'. Roles must be a list."

                if not all(role in org_roles for role in roles):
                    logger.error(f"Invalid roles for user '{username}': {roles}. Expected one of {org_roles}.")
                    return False, f"Invalid roles for user '{username}': Only organization-level roles are allowed."

                if username in usernames:
                    return False, f"Duplicate username '{username}' found in the input list."
                usernames.add(username)

            # Step 2: Create users after validation
            for user in users:
                username = user.get('username')
                password = user.get('password') or ''.join(random.choices(string.ascii_letters + string.digits, k=12))
                hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

                # Check if the user already exists
                user_exists, _ = await self.user_exists(username)
                if user_exists:
                    logger.warning(f"User creation skipped for '{username}': Username already exists.")
                    existing_users.append(username)  # Track existing users
                    continue

                # Build user data
                user_data = {
                    'username': username,
                    'hashed_password': hashed_password,
                    'projects': [],
                    'org_roles': user.get('org_roles', []),
                    **self._audit_create(acting_user),
                }

                await self.db_manager.insert_document('users', user_data)
                logger.info(f"User '{username}' created successfully.")
                created_users.append(user_data)

            if not created_users:
                return False, "No new users were created. All users already exist."

            # Step 3: Send welcome email with BCC to all created users
            reset_link = f"{self.domain or ''}/enable-password-reset"

            email_body = self.email_service.generate_standard_html(
                title="Welcome to Qubiva!",
                content=f"""
                <p>Hello,</p>
                <p>You have been added to <strong>{self.domain}</strong>.</p>
                <p>To set your password and access your account, please click the link below:</p>
                <p style="margin: 20px 0;">
                    <a href="{reset_link}" style="background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">Set Your Password</a>
                </p>
                <p>If the button doesn't work, copy and paste this link:</p>
                <p style="color: #666; font-size: 12px;">{reset_link}</p>
                """
            )

            def send_email_background():
                try:
                    self.email_service.send_email(
                        subject=f"Welcome to {self.domain}",
                        body=email_body,
                        bcc=[user['username'] for user in created_users]
                    )
                    logger.info(f"Welcome emails sent to {len(created_users)} users")
                except Exception as e:
                    logger.error(f"Exception sending welcome emails: {str(e)}")

            threading.Thread(target=send_email_background, daemon=True).start()

            final_message = f"{len(created_users)} new user(s) were created successfully."
            if existing_users:
                final_message += f" {len(existing_users)} user(s) already exist."
            final_message += " Welcome emails will be sent shortly."

            return True, final_message

        except Exception as e:
            logger.error(f"Failed to create users: {str(e)}")
            return False, f"Failed to create users: {str(e)}"

    async def modify_users_org_roles(self, users: List[dict], acting_user: str = None) -> Tuple[bool, str]:
        """
        Modify organization-level roles for multiple users without sending email notifications.

        :param users: A list of dictionaries, each containing 'username' and 'org_roles' (updated list of roles).
        :return: Tuple indicating success/failure and message.
        """
        logger.debug(users)
        modified_count = 0
        unchanged_count = 0

        try:
            for user in users:
                username = user.get('username')
                new_roles = user.get('org_roles') or []  # <- FIX: Ensure list

                # Ensure new_roles is actually a list
                if not isinstance(new_roles, list):
                    new_roles = []

                # Fetch the current user data to check existing roles
                user_exists, current_user_data = await self.user_exists(username)
                if not user_exists:
                    logger.warning(f"User '{username}' does not exist.")
                    continue  # Skip to the next user if the current one doesn't exist

                # Get current roles, ensuring it's always a list
                current_roles = current_user_data.get('org_roles') or []  # <- FIX: Ensure list
                if not isinstance(current_roles, list):
                    current_roles = []

                # Check if the roles have changed
                if set(current_roles) != set(new_roles):
                    # Update roles in the database
                    update_result = await self.db_manager.update_one_document(
                        'users',
                        {'username': username},
                        {'$set': {'org_roles': new_roles, **self._audit_update(acting_user)}}
                    )
                    if update_result['modified_count'] > 0:
                        modified_count += 1
                    else:
                        logger.warning(f"Failed to update roles for '{username}'.")
                else:
                    unchanged_count += 1

            # Construct the response message
            message = f"{modified_count} user(s) modified, {unchanged_count} user(s) unchanged."
            return True, message if modified_count > 0 else "No users were modified."

        except Exception as e:
            logger.error(f"An error occurred while modifying user roles: {str(e)}")
            return False, f"Failed to modify user roles: {str(e)}"

    async def delete_users(self, usernames: List[str], acting_user: str = None) -> Tuple[bool, str]:
        """
        Delete multiple users from the users collection and remove them from all projects they are associated with.

        :param usernames: A list of usernames of the users to delete.
        :return: Tuple indicating success/failure and message.
        """
        if not usernames:
            return False, "No usernames provided for deletion."

        deleted_users = []
        not_found_users = []
        failed_users = []

        for username in usernames:
            # Check if the user exists
            user_exists, user_data = await self.user_exists(username)
            if not user_exists:
                not_found_users.append(username)
                continue

            # Remove user from all projects they are a member of
            projects = user_data.get('projects', [])
            for project_name in projects:
                update_result = await self.db_manager.update_one_document(
                    'projects',
                    {'project_name': project_name},
                    {'$pull': {'members': {'username': username}}}
                )
                if update_result['matched_count'] == 0:
                    logger.warning(f"Project '{project_name}' not found when attempting to remove user '{username}'")

            # Delete the user from the users collection
            delete_result = await self.db_manager.delete_document('users', {'username': username})
            if delete_result > 0:
                deleted_users.append(username)
            else:
                failed_users.append(username)

        # Send BCC email notification to deleted users (async/non-blocking)
        if deleted_users:
            app_url = self.domain or 'Qubiva'

            email_body = self.email_service.generate_standard_html(
                title="Access Revoked",
                content=f"""
                <p>Hello,</p>
                <p>Your access to <strong>{app_url}</strong> has been revoked.</p>
                <p>If you have questions or believe this is an error, please contact support.</p>
                """
            )

            # Send email in background (non-blocking)
            def send_email_background():
                try:
                    self.email_service.send_email(
                        subject=f"Access Revoked - {self.domain}",
                        body=email_body,
                        bcc=deleted_users
                    )
                    logger.info(f"Revocation emails sent to {len(deleted_users)} users")
                except Exception as e:
                    logger.error(f"Exception sending revocation emails: {str(e)}")

            threading.Thread(target=send_email_background, daemon=True).start()

        # Construct the final response message
        message_parts = []
        if deleted_users:
            message_parts.append(f"{len(deleted_users)} user(s) deleted successfully.")
        if not_found_users:
            message_parts.append(f"{len(not_found_users)} user(s) not found.")
        if failed_users:
            message_parts.append(f"{len(failed_users)} user(s) could not be deleted.")

        return True if deleted_users else False, " ".join(message_parts)

    async def create_password_reset_token(self, username: str, expiry_hours: int = 1) -> str:
        """
        Generates a JWT token for password reset with a specified expiry time in hours.

        :param username: Username to include in the JWT token.
        :param expiry_hours: Expiration time for the token in hours.
        :return: Encrypted JWT token string.
        """
        # Create a token with custom expiration
        token = self.kms_manager.create_jwt(subject=username, expiry_hours=expiry_hours)
        return token

    async def send_password_reset_email(self, username: str):
        """
        Sends a password reset email containing a JWT token link to the user.

        :param username: The username/email of the user requesting a password reset.
        :return: Tuple indicating success/failure and message.
        """
        try:
            # Check if the user exists
            user_exists, _ = await self.user_exists(username)
            if not user_exists:
                return False, "User does not exist"

            # Generate the reset token
            try:
                token = await self.create_password_reset_token(username)
            except Exception as e:
                logger.error(f"Failed to create password reset token for '{username}': {e}")
                return False, "Failed to generate password reset token"

            reset_link = f"{self.domain or ''}/reset-password?token={token}"

            # Send the email with the reset link using HTML template
            try:
                html_body = self.email_service.generate_standard_html(
                    title="Password Reset Request",
                    content=f"""
                    <p>Hi there,</p>
                    <p>We received a request to reset your password for your Qubiva account.</p>
                    <p>Click the button below to reset your password:</p>
                    <p style="text-align: center; margin: 30px 0;">
                        <a href="{reset_link}"
                           style="display: inline-block; padding: 12px 24px; background-color: #007bff; color: white; text-decoration: none; border-radius: 4px; font-weight: 500;">
                            Reset Password
                        </a>
                    </p>
                    <p>Or copy and paste this link into your browser:</p>
                    <p style="background-color: #f8f9fa; padding: 10px; border-radius: 4px; word-break: break-all; font-family: monospace; font-size: 0.9em;">
                        {reset_link}
                    </p>
                    <p style="margin-top: 20px; color: #6c757d; font-size: 0.9em;">
                        <strong>Note:</strong> This link will expire in 1 hour for security reasons.
                    </p>
                    <p style="color: #6c757d; font-size: 0.9em;">
                        If you didn't request this password reset, you can safely ignore this email.
                    </p>
                    """
                )
                success, message = self.email_service.send_email(
                    subject="Password Reset Request",
                    body=html_body,
                    recipients=[username]
                )
                if not success:
                    logger.error(f"Failed to send password reset email to '{username}': {message}")
                    return False, message
                logger.info(f"Password reset email sent to '{username}'")
                return True, "Password reset email sent successfully"
            except Exception as e:
                logger.error(f"Exception occurred while sending password reset email to '{username}': {e}")
                return False, "Failed to send password reset email"

        except Exception as e:
            logger.error(f"An unexpected error occurred during password reset process for '{username}': {e}")
            return False, "An unexpected error occurred during password reset"

    async def reset_password(self, token: str, new_password: str):
        """
        Verifies the JWT token and resets the password if valid.

        :param token: JWT token to verify.
        :param new_password: The new password to set for the user.
        :return: Tuple indicating success/failure and message.
        """
        try:
            # Verify the JWT token
            payload = self.kms_manager.verify_jwt(token)
            username = payload.get("sub")
            if not username:
                return False, "Invalid token"

            user_exists, _ = await self.user_exists(username)
            if not user_exists:
                return False, "User does not exist"

            # Hash the new password and update the user's record
            hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            await self.db_manager.update_one_document(
                'users',
                {'username': username},
                {'$set': {'hashed_password': hashed_password}}
            )
            logger.info(f"Password reset successfully for '{username}'")
            return True, "Password reset successful"

        except jwt.ExpiredSignatureError:
            return False, "The reset link has expired"
        except jwt.InvalidTokenError:
            return False, "Invalid reset link"
        except Exception as e:
            logger.error(f"Failed to reset password: {str(e)}")
            return False, f"Failed to reset password: {str(e)}"

    async def user_exists(self, username):
        try:
            user = await self.db_manager.find_document('users', {'username': username})
            if user:
                return True, user
            return False, "User not found"
        except Exception as e:
            logger.error(f"Failed to check if user '{username}' exists: {str(e)}")
            return False, f"Failed to check user existence: {str(e)}"

    async def deactivate_user(self, username: str, reason: str, acting_user: str = None) -> Tuple[bool, str]:
        """
        Deactivate a user (soft delete).
        Used for removing stale SSO users or revoking access.

        Args:
            username: User's email/username
            reason: Reason for deactivation

        Returns:
            Tuple of (success, message)
        """
        try:
            update_result = await self.db_manager.update_one_document(
                'users',
                {'username': username},
                {
                    '$set': {
                        'active': False,
                        'deactivated_at': datetime.utcnow(),
                        'deactivation_reason': reason,
                        **self._audit_update(acting_user),
                    }
                }
            )

            if update_result['matched_count'] > 0:
                logger.info(f"Deactivated user: {username}. Reason: {reason}")
                return True, f"User {username} deactivated successfully"
            else:
                return False, f"User {username} not found"

        except Exception as e:
            logger.error(f"Failed to deactivate user {username}: {str(e)}")
            return False, f"Failed to deactivate user: {str(e)}"

    async def reactivate_user(self, username: str, acting_user: str = None) -> Tuple[bool, str]:
        """
        Reactivate a previously deactivated user.

        Args:
            username: User's email/username

        Returns:
            Tuple of (success, message)
        """
        try:
            update_result = await self.db_manager.update_one_document(
                'users',
                {'username': username},
                {
                    '$set': {
                        'active': True,
                        'reactivated_at': datetime.utcnow(),
                        **self._audit_update(acting_user),
                    },
                    '$unset': {
                        'deactivated_at': '',
                        'deactivation_reason': ''
                    }
                }
            )

            if update_result['matched_count'] > 0:
                logger.info(f"Reactivated user: {username}")
                return True, f"User {username} reactivated successfully"
            else:
                return False, f"User {username} not found"

        except Exception as e:
            logger.error(f"Failed to reactivate user {username}: {str(e)}")
            return False, f"Failed to reactivate user: {str(e)}"
