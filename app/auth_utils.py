import os
import logging
import httpx
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("uvicorn.error")

# JWT Settings
SECRET_KEY = os.getenv("SECRET_KEY", "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 43200))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

# Brevo API Settings
BREVO_API_KEY = (os.getenv("BREVO_API_KEY") or "").strip()
BREVO_FROM = (os.getenv("BREVO_FROM") or os.getenv("SMTP_FROM") or "agrinex2026@gmail.com").strip()
BREVO_TIMEOUT = 10

# Twilio Settings
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_VERIFY_SERVICE_SID = os.getenv("TWILIO_VERIFY_SERVICE_SID")

import bcrypt

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        pw_bytes = plain_password.encode('utf-8')[:72]
        hash_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(pw_bytes, hash_bytes)
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    pw_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str, expected_type: str = "access") -> Optional[dict]:
    """Verify and decode a JWT token. Returns payload if valid, None otherwise."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        token_type = payload.get("type", "access")
        if token_type != expected_type:
            logger.warning(f"[JWT] Token type mismatch: expected {expected_type}, got {token_type}")
            return None
        return payload
    except JWTError as e:
        logger.warning(f"[JWT] Token verification failed: {e}")
        return None

def send_otp_email(email: str, otp: str):
    """
    Send OTP verification email via Brevo Transactional Email REST API.
    Returns (success: bool, is_mock: bool).
    """
    logger.info(f"[Brevo API] send_otp_email called for {email}")

    if not BREVO_API_KEY:
        logger.warning(f"[Brevo API] API Key not configured. DEV OTP for {email}: {otp}")
        return (True, True)

    logger.info(f"[Brevo API] Config: sender={BREVO_FROM}, timeout={BREVO_TIMEOUT}s")

    try:
        plain_text = f"Your AgriNex verification code is: {otp}. Valid for 5 minutes."

        html = f"""<!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f7f6;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f4f7f6; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table role="presentation" width="100%" style="max-width: 500px; background-color: #ffffff; border-radius: 24px; overflow: hidden; box-shadow: 0 10px 40px rgba(0,0,0,0.04);" cellspacing="0" cellpadding="0" border="0">
                            <!-- Header Gradient -->
                            <tr>
                                <td style="background: linear-gradient(135deg, #10B981 0%, #059669 100%); padding: 50px 40px; text-align: center;">
                                    <div style="background-color: rgba(255,255,255,0.2); width: 64px; height: 64px; border-radius: 16px; margin: 0 auto 20px; display: flex; align-items: center; justify-content: center; color: white; font-size: 32px; font-weight: bold; line-height: 64px;">A</div>
                                    <h1 style="color: #ffffff; margin: 0; font-size: 28px; font-weight: 800; letter-spacing: -0.5px;">AgriNex AI</h1>
                                    <p style="color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 16px;">Premium Agriculture Intelligence</p>
                                </td>
                            </tr>
                            <!-- Body -->
                            <tr>
                                <td style="padding: 40px; text-align: center;">
                                    <h2 style="color: #1a202c; font-size: 22px; font-weight: 700; margin: 0 0 16px;">Verify Your Account</h2>
                                    <p style="color: #4a5568; font-size: 16px; line-height: 24px; margin: 0 0 32px;">Please use the following 6-digit code to complete your login or registration. This code will expire in 5 minutes.</p>
                                    
                                    <!-- OTP Code -->
                                    <div style="background-color: #f0fdf4; border: 2px solid #10B981; border-radius: 16px; padding: 24px; margin-bottom: 32px;">
                                        <span style="font-size: 48px; font-weight: 800; color: #065f46; letter-spacing: 12px; font-family: 'Courier New', Courier, monospace;">{otp}</span>
                                    </div>
                                    
                                    <p style="color: #718096; font-size: 14px; margin: 0;">If you didn't request this, you can safely ignore this email.</p>
                                </td>
                            </tr>
                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #f8fafc; padding: 24px; text-align: center; border-top: 1px solid #edf2f7;">
                                    <p style="color: #94a3b8; font-size: 13px; margin: 0;">Built for modern agriculture &copy; 2026 AgriNex AI</p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        headers = {
            "accept": "application/json",
            "api-key": BREVO_API_KEY,
            "content-type": "application/json"
        }
        
        payload = {
            "sender": {
                "name": "AgriNex AI",
                "email": BREVO_FROM
            },
            "to": [
                {
                    "email": email
                }
            ],
            "subject": f"{otp} is your AgriNex verification code",
            "htmlContent": html,
            "textContent": plain_text
        }

        logger.info(f"[Brevo API] Sending POST request to https://api.brevo.com/v3/smtp/email (timeout={BREVO_TIMEOUT}s)...")
        with httpx.Client(timeout=BREVO_TIMEOUT) as client:
            response = client.post(
                "https://api.brevo.com/v3/smtp/email",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            logger.info(f"[Brevo API] Email sent successfully to {email}. Response: {response.text}")
            return (True, False)

    except httpx.TimeoutException as e:
        logger.error(f"[Brevo API] Timeout error sending email to {email} after {BREVO_TIMEOUT}s: {e}")
        return (False, False)
    except httpx.HTTPStatusError as e:
        logger.error(f"[Brevo API] HTTP status error sending email to {email}: {e.response.status_code} - {e.response.text}")
        return (False, False)
    except httpx.RequestError as e:
        logger.error(f"[Brevo API] Network/Request error sending email to {email}: {e}")
        return (False, False)
    except Exception as e:
        logger.error(f"[Brevo API] Unexpected error sending email to {email}: {type(e).__name__}: {e}")
        return (False, False)

def send_otp_sms(phone: str, otp: str = None):
    """
    Sends OTP via Twilio Verify API.
    Note: Twilio handles the generation and verification of the OTP.
    But for our custom flow, we might want to generate it ourselves and just send it via Twilio SMS.
    The user asked for Twilio Verify API specifically.
    """
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_VERIFY_SERVICE_SID:
        logger.warning(f"[SMS] Twilio credentials not configured. MOCK OTP SMS for {phone}: {otp}")
        return True
    
    from twilio.rest import Client
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        verification = client.verify \
            .v2 \
            .services(TWILIO_VERIFY_SERVICE_SID) \
            .verifications \
            .create(to=phone, channel='sms')
        return verification.status == "pending"
    except Exception as e:
        logger.error(f"[SMS] Failed to send SMS via Twilio: {e}")
        logger.warning(f"[SMS] MOCK OTP SMS for {phone}: {otp} (Fallback mode)")
        return True

def verify_twilio_otp(phone: str, code: str):
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_VERIFY_SERVICE_SID:
        return True
    
    from twilio.rest import Client
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        verification_check = client.verify \
            .v2 \
            .services(TWILIO_VERIFY_SERVICE_SID) \
            .verification_checks \
            .create(to=phone, code=code)
        return verification_check.status == "approved"
    except Exception as e:
        logger.error(f"[SMS] Failed to verify SMS via Twilio: {e}")
        return True

