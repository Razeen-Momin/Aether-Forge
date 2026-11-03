# Sends email through Brevo's HTTPS API.
#
# Why not SMTP? Render's free web services block the SMTP ports
# (25, 465, 587), so smtplib would simply time out there. An HTTPS API
# call works everywhere.
#
# Environment variables (set them on Render, never in frontend code or GitHub):
#   BREVO_API_KEY     - API key created in the Brevo dashboard
#   MAIL_FROM_EMAIL   - a sender address you verified in Brevo
#   MAIL_FROM_NAME    - optional display name, defaults to "Aether Forge"
import os

import requests
from flask import current_app

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


class EmailNotConfigured(Exception):
    """The server has no email provider settings."""


class EmailSendError(Exception):
    """The provider could not be reached or rejected the message."""


def send_email(to_email, subject, text_body, html_body):
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("MAIL_FROM_EMAIL")
    sender_name = os.getenv("MAIL_FROM_NAME", "Aether Forge")

    if not api_key or not sender_email:
        raise EmailNotConfigured()

    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": text_body,
        "htmlContent": html_body,
    }

    try:
        response = requests.post(
            BREVO_SEND_URL,
            headers={
                "api-key": api_key,
                "accept": "application/json",
                "content-type": "application/json",
            },
            json=payload,
            timeout=15,
        )
    except requests.RequestException:
        current_app.logger.exception("Could not reach the email provider.")
        raise EmailSendError()

    if response.status_code not in (200, 201, 202):
        # Log the provider's reason (never the API key) to help debugging
        current_app.logger.error(
            "Email provider rejected the message: %s %s",
            response.status_code,
            response.text[:300],
        )
        raise EmailSendError()
