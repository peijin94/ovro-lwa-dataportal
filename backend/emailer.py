import smtplib
from email.message import EmailMessage
from typing import Optional

from backend.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM


def _format_bytes(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f} GB"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f} MB"
    if n >= 1_000:
        return f"{n / 1_000:.2f} KB"
    return f"{n} B"


def send_stage_email(
    to_email: str,
    download_url: str,
    file_count: int,
    total_size_bytes: int,
    start_time: str,
    end_time: str,
) -> None:
    """
    Send an email notifying the user that a staged dataset is ready.

    This is intended to be called from a FastAPI BackgroundTasks context so it
    does not block the HTTP response.
    """
    if not to_email:
        return
    if not SMTP_HOST or not SMTP_FROM:
        # Misconfigured email; log and exit silently.
        print("[EMAIL] SMTP not configured; skipping email send")
        return

    size_str = _format_bytes(total_size_bytes)
    subject = "OVRO-LWA staged data ready for download"
    body = (
        "Your requested OVRO-LWA data has been staged and is ready for download.\n\n"
        f"Time range (UTC): {start_time} – {end_time}\n"
        f"Number of files: {file_count}\n"
        f"Total size: {size_str}\n\n"
        f"Download link:\n{download_url}\n\n"
        "This link may be temporary; please download the data as soon as convenient.\n\n"
        "This message was sent from an unmonitored address "
        f"({SMTP_FROM}); replies are not read."
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"[EMAIL] Sent stage email to {to_email}")
    except Exception as exc:  # pragma: no cover - best-effort logging
        print(f"[EMAIL_ERROR] Failed to send stage email to {to_email}: {exc}")

