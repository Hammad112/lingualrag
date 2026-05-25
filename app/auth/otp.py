import secrets
import httpx
import logging

from app.config import settings

logger = logging.getLogger(__name__)


def generate_otp() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(settings.OTP_LENGTH))


async def send_otp_email(email: str, otp: str, purpose: str) -> None:
    """Send OTP via Resend if configured, always log to console in dev."""
    if settings.OTP_PRINT_TO_CONSOLE or not settings.RESEND_API_KEY:
        print("\n" + "=" * 60)
        print(f"  OTP for {email} ({purpose}): {otp}")
        print(f"  Expires in {settings.OTP_EXPIRE_MINUTES} minutes")
        print("=" * 60 + "\n")

    if not settings.RESEND_API_KEY:
        return

    subject = "Your LingualRAG verification code"
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:480px;margin:auto">
      <h2>LingualRAG verification</h2>
      <p>Your one-time code is:</p>
      <p style="font-size:32px;letter-spacing:6px;font-weight:700">{otp}</p>
      <p>It expires in {settings.OTP_EXPIRE_MINUTES} minutes.</p>
    </div>
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={
                    "from": settings.EMAIL_FROM,
                    "to": [email],
                    "subject": subject,
                    "html": html,
                },
            )
            if r.status_code >= 400:
                logger.error(
                    "Resend send FAILED (%s) from=%s to=%s body=%s",
                    r.status_code, settings.EMAIL_FROM, email, r.text,
                )
            else:
                logger.info("Resend email sent to %s (id=%s)", email, r.json().get("id"))
    except Exception as e:
        logger.error("Email send error: %s", e, exc_info=True)
