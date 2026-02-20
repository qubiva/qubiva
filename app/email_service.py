import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Tuple, Union, Dict, Any
import logging

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class EmailService:
    def __init__(self, sender_email: str):
        """
        Initialize the email service with SMTP configuration and sender email.
        :param sender_email: The email address that will be used as the 'From' address.
        """
        # SMTP config is optional by default.
        # Set SMTP_REQUIRED=true to enforce startup failure when misconfigured.
        self.smtp_host = os.getenv("SMTP_HOST", "").strip()
        self.smtp_port = os.getenv("SMTP_PORT", "587").strip()
        self.smtp_username = os.getenv("SMTP_USERNAME", "").strip()
        self.smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
        self.smtp_secure = os.getenv("SMTP_SECURE", "tls").strip().lower()
        self.smtp_required = os.getenv("SMTP_REQUIRED", "false").lower() == "true"

        missing_vars = [var for var, value in {
            "SMTP_HOST": self.smtp_host,
            "SMTP_USERNAME": self.smtp_username,
            "SMTP_PASSWORD": self.smtp_password,
        }.items() if not value]

        self.enabled = len(missing_vars) == 0
        if not self.enabled:
            message = f"SMTP not fully configured ({', '.join(missing_vars)} missing). Email sending will be disabled."
            if self.smtp_required:
                raise EnvironmentError(message)
            logger.warning(message)

        if self.smtp_secure not in {"tls", "ssl", "none"}:
            raise ValueError("SMTP_SECURE must be one of: tls, ssl, none")

        # Convert smtp_port to integer if it's a valid number
        try:
            self.smtp_port = int(self.smtp_port)
        except ValueError:
            raise ValueError("SMTP_PORT environment variable must be a valid integer.")

        self.sender_email = os.getenv("SMTP_FROM_EMAIL", sender_email)
        logger.info(f"EmailService initialized with sender email: {self.sender_email}")

    def send_email(self, subject: str, body: str, recipients: List[str] = None, bcc: List[str] = None) -> Tuple[bool, str]:
        if not self.enabled:
            logger.warning("Email sending skipped because SMTP is not configured")
            return False, "Email service is not configured"

        if not recipients and not bcc:
            logger.error("At least one recipient or BCC email is required")
            return False, "At least one recipient or BCC email is required"

        recipient_info = f"recipients: {recipients}" if recipients else f"BCC: {len(bcc) if bcc else 0} recipients"
        logger.info(f"Attempting to send email with subject: {subject} to {recipient_info}")

        # Ensure recipients and bcc are lists, defaulting to empty lists if None
        recipients = recipients or []
        bcc = bcc or []

        # Create the email message
        message = MIMEMultipart()
        message['From'] = self.sender_email
        if recipients:
            message['To'] = ", ".join(recipients)
        message['Subject'] = subject
        message.attach(MIMEText(body, 'html'))

        # Add BCC recipients in the headers for reference (some clients display them this way)
        if bcc:
            message['Bcc'] = ", ".join(bcc)

        try:
            # Establish connection to SMTP server
            if self.smtp_secure.lower() == "ssl":
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port)
                if self.smtp_secure.lower() == "tls":
                    server.starttls()

            server.login(self.smtp_username, self.smtp_password)

            # Combine recipients and BCCs for sending
            all_recipients = recipients + bcc

            # Send email
            server.sendmail(self.sender_email, all_recipients, message.as_string())
            server.quit()
            logger.info("Email sent successfully")
            return True, "Email sent successfully"
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            return False, f"Failed to send email: {str(e)}"

    def generate_standard_html(self, title: str, content: str, footer: str = None) -> str:
        """
        Generate a standardized HTML template for the email.
        :param title: The title of the email.
        :param content: The main content of the email.
        :param footer: The footer of the email (default is a thank you message).
        :return: A complete HTML string.
        """
        logger.info(f"Generating standard HTML with title: {title}")

        if footer is None:
            footer = """
            <p style="color: gray; font-size: 12px;">
                This is an automated message from <strong>Qubiva</strong>. Please do not reply to this email. If you need assistance,
                please contact your Qubiva administrator.
            </p>
            """

        html_template = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                .container {{ width: 90%; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }}
                .header {{ font-size: 20px; margin-bottom: 20px; font-weight: bold; }}
                .content {{ margin-bottom: 20px; }}
                .footer {{ font-size: 12px; color: #555; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">{title}</div>
                <div class="content">{content}</div>
                <div class="footer">{footer}</div>
            </div>
        </body>
        </html>
        """
        logger.info("Standard HTML generated successfully")
        return html_template

    def generate_dynamic_content(self, content: Union[Dict[str, Any], List[Dict[str, Any]], str]) -> str:
        """
        Generate HTML content dynamically based on the input type.
        :param content: The content to be converted to HTML. Can be a dictionary, list of dictionaries, or a string.
        :return: A string with the HTML representation of the content.
        """
        logger.info("Generating dynamic content based on the input type")

        if isinstance(content, dict):
            logger.debug(f"Generating HTML table for dictionary content: {content}")
            # Create an HTML table with a single "Details" header
            table_html = """
            <table border='1' style='border-collapse: collapse; width: 100%;'>
                <thead>
                    <tr>
                        <th colspan='2' style='padding: 8px; background-color: #f2f2f2;'>Details</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>"""
            # Add keys in the first row
            for key in content.keys():
                table_html += f"<td style='padding: 8px; font-weight: bold;'>{key}</td>"
            table_html += "</tr><tr>"
            # Add values in the second row
            for value in content.values():
                table_html += f"<td style='padding: 8px;'>{value}</td>"
            table_html += "</tr></tbody></table>"
            logger.info("HTML table generated for dictionary content")
            return table_html

        elif isinstance(content, list) and all(isinstance(item, dict) for item in content):
            logger.debug(f"Generating HTML table for list of dictionaries content: {content}")
            # Handle a list of dictionaries
            if not content:
                return "<p>No data available</p>"

            table_html = """
            <table border='1' style='border-collapse: collapse; width: 100%;'>
                <thead>
                    <tr>
                        <th colspan='2' style='padding: 8px; background-color: #f2f2f2;'>Details</th>
                    </tr>
                </thead>
                <tbody>"""

            for item in content:
                table_html += "<tr>"
                for key, value in item.items():
                    table_html += f"<td style='padding: 8px; font-weight: bold;'>{key}</td>"
                    table_html += f"<td style='padding: 8px;'>{value}</td>"
                table_html += "</tr>"

            table_html += "</tbody></table>"
            logger.info("HTML table generated for list of dictionaries content")
            return table_html

        elif isinstance(content, str):
            logger.debug(f"Generating paragraph for string content: {content}")
            # Return plain string wrapped in a paragraph
            return f"<p>{content}</p>"

        else:
            logger.warning("Unsupported content format provided")
            return "<p>Unsupported content format</p>"
