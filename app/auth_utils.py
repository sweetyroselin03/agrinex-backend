import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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

# SMTP Settings
SMTP_HOST = os.getenv("EXPO_PUBLIC_SMTP_HOST") or os.getenv("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT = int(os.getenv("EXPO_PUBLIC_SMTP_PORT") or os.getenv("SMTP_PORT") or 587)
SMTP_USER = os.getenv("SMTP_USER") or os.getenv("EMAIL_USER")
SMTP_PASS = os.getenv("SMTP_PASS") or os.getenv("EMAIL_PASS")
SMTP_FROM = os.getenv("EXPO_PUBLIC_SMTP_FROM") or os.getenv("SMTP_FROM") or SMTP_USER

# Twilio Settings
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_VERIFY_SERVICE_SID = os.getenv("TWILIO_VERIFY_SERVICE_SID")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    # Bcrypt has a 72-character limit, truncate to be safe and consistent
    return pwd_context.verify(plain_password[:72], hashed_password)

def get_password_hash(password):
    # Bcrypt has a 72-character limit, truncate to be safe
    return pwd_context.hash(password[:72])

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def send_otp_email(email: str, otp: str):
    """Returns (success: bool, is_mock: bool)"""
    if not SMTP_USER or not SMTP_PASS:
        logger.warning(f"[SMTP] SMTP not configured. DEV OTP for {email}: {otp}")
        return (True, True)
    
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"{otp} is your AgriNex verification code"
        msg["From"] = f"AgriNex AI <{SMTP_FROM}>"
        msg["To"] = email

        plain_text = f"Your AgriNex verification code is: {otp}. Valid for 5 minutes."

        html = f"""
        <!DOCTYPE html>
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
        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(html, "html"))

        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        return (True, False)
    except Exception as e:
        logger.error(f"[SMTP] Failed to send email via SMTP to {email}: {e}")
        return (False, False)

def validate_smtp_credentials():
    """Validates SMTP configuration and credentials on startup by logging in."""
    if not SMTP_USER or not SMTP_PASS:
        logger.warning("[SMTP] Configuration missing or incomplete. Email sending will run in MOCK mode.")
        return False
    try:
        logger.info(f"[SMTP] Testing SMTP connection to {SMTP_HOST}:{SMTP_PORT} using {SMTP_USER}...")
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.quit()
        logger.info("[SMTP] Connection and credentials verified successfully!")
        return True
    except Exception as e:
        logger.error(f"[SMTP] Connection verification failed: {e}")
        return False

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
        print(f"Failed to verify SMS via Twilio: {e}")
        return True

