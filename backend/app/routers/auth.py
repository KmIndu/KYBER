"""Authentication routes — SSO login, OAuth2 callback, OTP email login, user info, logout."""

from __future__ import annotations

import hashlib
import logging
import random
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.auth.jwt_handler import create_access_token
from app.auth.oauth2 import (
    exchange_code_for_tokens,
    fetch_userinfo,
    get_authorization_url,
    validate_state,
)
from app.utils.config import settings

logger = logging.getLogger(settings.APP_NAME)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ---------------------------------------------------------------------------
# In-memory OTP store: key = email, value = {otp, expires_at, attempts}
# ---------------------------------------------------------------------------
_otp_store: dict[str, dict] = {}


@router.get("/config")
async def auth_config():
    """Return public auth configuration so the frontend knows whether SSO is enabled."""
    sso_configured = bool(settings.OAUTH2_CLIENT_ID and settings.OAUTH2_AUTHORIZATION_URL)
    return {
        "auth_enabled": settings.AUTH_ENABLED,
        "sso_configured": sso_configured,
        "provider": settings.OAUTH2_PROVIDER if settings.AUTH_ENABLED else None,
        "session_timeout_minutes": settings.JWT_EXPIRY_MINUTES,
    }


@router.get("/login")
async def login():
    """Redirect the browser to the OAuth2 provider's authorization page."""
    if not settings.AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="Authentication is not enabled")
    url, _ = get_authorization_url()
    return {"authorization_url": url}


@router.get("/callback")
async def callback(code: str = Query(...), state: str = Query(...)):
    """Handle the OAuth2 callback — exchange code, fetch user info, issue JWT."""
    if not validate_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter")

    try:
        tokens = await exchange_code_for_tokens(code)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {exc}")

    access_token = tokens.get("access_token", "")

    # Fetch user profile from provider
    try:
        userinfo = await fetch_userinfo(access_token)
    except Exception:
        # Fallback: decode id_token if userinfo endpoint fails
        userinfo = {}

    user_data = {
        "sub": userinfo.get("sub") or userinfo.get("oid") or "unknown",
        "name": userinfo.get("name") or userinfo.get("preferred_username") or "",
        "email": userinfo.get("email") or userinfo.get("upn") or "",
        "picture": userinfo.get("picture") or "",
    }

    # Create our own session JWT
    app_token = create_access_token(user_data)

    return JSONResponse({"token": app_token, "user": user_data})


@router.post("/demo-login")
async def demo_login():
    """Issue a JWT for demo/development usage when no SSO provider is configured."""
    user_data = {
        "sub": "anonymous",
        "name": "Anonymous",
        "email": "",
        "picture": "",
        "guest": True,
        "role": "guest",
    }
    token = create_access_token(user_data)
    return JSONResponse({"token": token, "user": user_data})


@router.post("/guest-login")
async def guest_login():
    """Issue a JWT for anonymous/guest access."""
    return await demo_login()


def _generate_otp() -> str:
    """Generate a 6-digit OTP."""
    return f"{random.randint(100000, 999999)}"


def _build_otp_html(otp: str) -> str:
    """Build the HTML body for the OTP email — KYBER branded with Star Wars theme."""
    import random as _rnd
    import base64 as _b64
    from pathlib import Path as _Path
    _logo_path = _Path(__file__).resolve().parents[2] / "frontend" / "public" / "logo.jpg"
    try:
        _logo_b64 = _b64.b64encode(_logo_path.read_bytes()).decode()
        _logo_uri = f"data:image/jpeg;base64,{_logo_b64}"
    except Exception:
        _logo_uri = ""
    digits = "".join(
        f'<td style="width:48px;height:56px;text-align:center;vertical-align:middle;font-size:28px;font-weight:700;'
        f"font-family:'Courier New',Consolas,monospace;color:#00FF9F;line-height:56px;"
        f'background:#0A3D3A;border:1px solid #00FF9F33;border-radius:8px;letter-spacing:2px;padding:0">{d}</td>'
        for d in otp
    )
    expiry = settings.OTP_EXPIRY_SECONDS // 60

    yoda_quotes = [
        "Do or do not. There is no try… but there is synthetic data.",
        "Patience you must have, young Padawan. Good data takes time.",
        "Strong with the Force, your test data will be.",
        "Much to learn, you still have… about edge cases.",
        "The dark side of production data, avoid you must.",
        "Size matters not. A single schema, powerful it can be.",
        "Truly wonderful, the mind of a data engineer is.",
        "In a dark place we find ourselves, when NULL values appear.",
        "Fear of bad data leads to anger. Anger leads to bugs.",
        "Always two there are — a primary key and a foreign key.",
    ]
    yoda_quote = _rnd.choice(yoda_quotes)

    # Generate CSS stars for the header
    stars_css = ""
    for i in range(30):
        x = _rnd.randint(0, 100)
        y = _rnd.randint(0, 100)
        size = _rnd.choice([1, 1, 1, 2])
        opacity = _rnd.uniform(0.3, 0.9)
        stars_css += f".s{i}{{position:absolute;left:{x}%;top:{y}%;width:{size}px;height:{size}px;background:white;border-radius:50%;opacity:{opacity}}}"

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>{stars_css}</style>
</head>
<body style="margin:0;padding:0;background:#0B0F14;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
  <div style="display:none;max-height:0;overflow:hidden">Your KYBER holocron access code is {otp} — expires in {expiry} min.&#8199;&#65279;&#847; &#8199;&#65279;&#847; &#8199;&#65279;&#847;</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0B0F14;padding:40px 0">
    <tr><td align="center">
      <table role="presentation" width="520" cellpadding="0" cellspacing="0" style="background:#111820;border-radius:16px;border:1px solid #0A3D3A;overflow:hidden;box-shadow:0 0 40px rgba(0,255,159,0.05)">

        <!-- Header with starfield -->
        <tr><td style="background:#0B0F14;padding:32px 32px 28px;text-align:center;border-bottom:2px solid transparent;background-image:linear-gradient(#0B0F14,#0B0F14),linear-gradient(90deg,transparent,#00FF9F,#00E6CC,transparent);background-origin:padding-box,border-box;background-clip:padding-box,border-box;position:relative">
          <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto"><tr>
            <td style="width:40px;height:40px;vertical-align:middle;padding:0"><img src="{_logo_uri}" alt="KYBER" width="40" height="40" style="display:block;border-radius:10px;width:40px;height:40px;object-fit:cover;box-shadow:0 0 20px rgba(0,255,159,0.3)"></td>
            <td style="padding-left:14px;color:#00FF9F;font-family:'Orbitron',sans-serif;font-size:20px;font-weight:700;letter-spacing:4px">KYBER</td>
          </tr></table>
          <p style="margin:12px 0 0;font-size:11px;color:#00FF9F44;letter-spacing:2px;font-family:'Orbitron',sans-serif">SYNTHETIC DATA FORGE</p>
        </td></tr>

        <!-- Lightsaber accent line -->
        <tr><td style="height:2px;background:linear-gradient(90deg,transparent 5%,#00FF9F 30%,#00E6CC 70%,transparent 95%);box-shadow:0 0 8px rgba(0,255,159,0.4)"></td></tr>

        <!-- Body -->
        <tr><td style="padding:40px 36px 32px">
          <p style="margin:0 0 4px;font-size:13px;color:#00E6CC;font-weight:600;letter-spacing:1px;text-transform:uppercase">Holocron Access Code</p>
          <p style="margin:0 0 8px;font-size:24px;font-weight:600;color:#E0E0E0">Greetings, Jedi</p>
          <p style="margin:0 0 32px;font-size:15px;color:#9CA3AF;line-height:1.6">
            Enter the following code to access the Data Forge. This code expires in <strong style="color:#00FF9F">{expiry} minutes</strong>.
          </p>

          <!-- OTP digits -->
          <table role="presentation" cellpadding="0" cellspacing="10" style="margin:0 auto 32px">
            <tr>{digits}</tr>
          </table>

          <!-- Lightsaber divider -->
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px">
            <tr><td style="height:1px;background:linear-gradient(90deg,transparent,#0A3D3A,transparent)"></td></tr>
          </table>

          <!-- Yoda wisdom -->
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#0A3D3A22;border-radius:10px;border:1px solid #0A3D3A44;margin:0 0 24px">
            <tr><td style="padding:16px 20px">
              <p style="margin:0 0 6px;font-size:10px;color:#00E6CC88;font-weight:700;letter-spacing:2px;text-transform:uppercase">Yoda says</p>
              <p style="margin:0;font-size:13px;color:#9CA3AF;font-style:italic;line-height:1.5">"{yoda_quote}"</p>
            </td></tr>
          </table>

          <!-- Security note -->
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr>
            <td style="width:22px;vertical-align:top;padding-top:2px">
              <div style="width:18px;height:18px;background:#9D4EDD22;border:1px solid #9D4EDD44;border-radius:50%;text-align:center;line-height:18px;font-size:11px;font-weight:700;color:#9D4EDD">!</div>
            </td>
            <td style="padding-left:10px;font-size:13px;color:#6B7280;line-height:1.5">
              If you didn't request this code, you can safely ignore this email. Never share your verification code with anyone.
            </td>
          </tr></table>
        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#0B0F14;padding:24px 32px;border-top:1px solid #0A3D3A;text-align:center">
          <p style="margin:0 0 6px;font-size:11px;color:#00FF9F33;font-family:'Orbitron',sans-serif;letter-spacing:2px">JEDI &middot; KYBER</p>
          <p style="margin:0 0 4px;font-size:12px;color:#4B5563">
            &copy; {__import__('datetime').datetime.now().year} Synthetic Data Forge
          </p>
          <p style="margin:0;font-size:11px;color:#4B556388;font-style:italic">May the Synthetic Data Be With You</p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _send_via_outlook(email: str, otp: str) -> bool:
    """Send OTP using the local Outlook application via COM automation."""
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # 0 = MailItem
        mail.To = email
        mail.Subject = f"KYBER Holocron Code: {otp}"
        mail.HTMLBody = _build_otp_html(otp)
        mail.Send()
        logger.info("[OTP] Email sent to %s via Outlook", email)
        return True
    except ImportError:
        logger.warning("[OTP] pywin32 not installed — cannot use Outlook")
        return False
    except Exception as exc:
        logger.error("[OTP] Outlook send failed for %s: %s", email, exc)
        return False


def _send_via_graph(email: str, otp: str) -> bool:
    """Send OTP via Microsoft Graph API (works anywhere — server, Docker, cloud)."""
    if not all([settings.GRAPH_CLIENT_ID, settings.GRAPH_CLIENT_SECRET, settings.GRAPH_TENANT_ID]):
        return False
    try:
        import msal
        import requests as http_requests

        # Acquire token using client credentials (app-only)
        app = msal.ConfidentialClientApplication(
            settings.GRAPH_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{settings.GRAPH_TENANT_ID}",
            client_credential=settings.GRAPH_CLIENT_SECRET,
        )
        token_result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])

        if "access_token" not in token_result:
            logger.error("[OTP] Graph API token acquisition failed: %s", token_result.get("error_description", "Unknown error"))
            return False

        # Send email via Graph API
        send_url = f"https://graph.microsoft.com/v1.0/users/{settings.GRAPH_SENDER_EMAIL}/sendMail"
        mail_body = {
            "message": {
                "subject": f"KYBER Holocron Code: {otp}",
                "body": {
                    "contentType": "HTML",
                    "content": _build_otp_html(otp),
                },
                "toRecipients": [
                    {"emailAddress": {"address": email}}
                ],
            },
            "saveToSentItems": "false",
        }

        resp = http_requests.post(
            send_url,
            json=mail_body,
            headers={
                "Authorization": f"Bearer {token_result['access_token']}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )

        if resp.status_code == 202:
            logger.info("[OTP] Email sent to %s via Microsoft Graph API", email)
            return True
        else:
            logger.error("[OTP] Graph API send failed (%s): %s", resp.status_code, resp.text)
            return False
    except ImportError:
        logger.warning("[OTP] msal/requests not installed — cannot use Graph API")
        return False
    except Exception as exc:
        logger.error("[OTP] Graph API send failed for %s: %s", email, exc)
        return False


def _send_via_smtp(email: str, otp: str) -> bool:
    """Send OTP via SMTP relay."""
    if not settings.SMTP_HOST:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = settings.SMTP_FROM
        msg["To"] = email
        msg["Subject"] = f"KYBER Holocron Code: {otp}"
        msg.attach(MIMEText(_build_otp_html(otp), "html"))

        if settings.SMTP_USE_TLS:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)

        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, email, msg.as_string())
        server.quit()
        logger.info("[OTP] Email sent to %s via SMTP", email)
        return True
    except Exception as exc:
        logger.error("[OTP] SMTP send failed for %s: %s", email, exc)
        return False


def _send_otp_email(email: str, otp: str) -> bool:
    """Send OTP email — tries Graph API, then Outlook COM, then SMTP, then console."""
    # 1. Try Microsoft Graph API (works in production/Docker/cloud)
    if _send_via_graph(email, otp):
        return True

    # 2. Try Outlook COM (works on local Windows with Outlook installed)
    if _send_via_outlook(email, otp):
        return True

    # 3. Try SMTP relay
    if _send_via_smtp(email, otp):
        return True

    # 4. Fallback — log to console
    logger.info("[OTP] Code for %s: %s  (fallback — printing to console)", email, otp)
    return False


@router.post("/send-otp")
async def send_otp(payload: dict):
    """Generate a 6-digit OTP and email it to the user."""
    email = (payload.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    otp = _generate_otp()

    email_sent = _send_otp_email(email, otp)
    if not email_sent:
        _otp_store.pop(email, None)
        raise HTTPException(status_code=502, detail="OTP could not be sent. Please try again later.")

    _otp_store[email] = {
        "otp": otp,
        "expires_at": time.time() + settings.OTP_EXPIRY_SECONDS,
        "attempts": 0,
    }

    return JSONResponse({
        "message": "OTP sent to your email address.",
        "email_sent": True,
        "expires_in": settings.OTP_EXPIRY_SECONDS,
    })


@router.post("/verify-otp")
async def verify_otp(payload: dict):
    """Verify OTP and issue a JWT on success."""
    email = (payload.get("email") or "").strip().lower()
    otp = (payload.get("otp") or "").strip()

    if not email or not otp:
        raise HTTPException(status_code=400, detail="Email and OTP are required.")

    record = _otp_store.get(email)
    if not record:
        raise HTTPException(status_code=400, detail="No OTP requested for this email. Please request a new code.")

    # Check expiry
    if time.time() > record["expires_at"]:
        _otp_store.pop(email, None)
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new code.")

    # Limit brute-force attempts
    if record["attempts"] >= 5:
        _otp_store.pop(email, None)
        raise HTTPException(status_code=429, detail="Too many attempts. Please request a new code.")

    record["attempts"] += 1

    if record["otp"] != otp:
        remaining = 5 - record["attempts"]
        raise HTTPException(status_code=400, detail=f"Invalid OTP. {remaining} attempt(s) remaining.")

    # OTP valid — clean up and issue JWT
    _otp_store.pop(email, None)

    local_part = email.split("@")[0]
    name = " ".join(word.capitalize() for word in local_part.replace(".", " ").replace("_", " ").replace("-", " ").split())

    user_data = {
        "sub": email,
        "name": name,
        "email": email,
        "picture": "",
    }
    token = create_access_token(user_data)
    return JSONResponse({"token": token, "user": user_data})


@router.post("/email-login")
async def email_login(payload: dict):
    """Legacy email login — redirects to OTP flow."""
    return await send_otp(payload)


@router.get("/me")
async def me(token: str = Query(...)):
    """Validate a JWT and return the user profile."""
    from app.auth.jwt_handler import decode_access_token

    claims = decode_access_token(token)
    if claims is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return {
        "sub": claims.get("sub"),
        "name": claims.get("name"),
        "email": claims.get("email"),
        "picture": claims.get("picture", ""),
    }


@router.post("/refresh")
async def refresh(payload: dict):
    """Extend session — issue a new JWT if the current one is still valid."""
    from app.auth.jwt_handler import decode_access_token
    token = payload.get("token", "")
    claims = decode_access_token(token)
    if claims is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired or invalid")
    user_data = {
        "sub": claims.get("sub"),
        "name": claims.get("name"),
        "email": claims.get("email"),
        "picture": claims.get("picture", ""),
    }
    new_token = create_access_token(user_data)
    return JSONResponse({"token": new_token, "user": user_data})


@router.post("/logout")
async def logout():
    """Logout — client should discard token.  Returns provider logout URL if available."""
    result: dict = {"message": "Logged out successfully"}
    if settings.OAUTH2_LOGOUT_URL:
        result["logout_url"] = settings.OAUTH2_LOGOUT_URL
    return result
