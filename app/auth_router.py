from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import random
import os
import logging
from . import models, schemas, auth_utils
from .database import get_db

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger("uvicorn.error")

@router.post("/send-otp")
def send_otp(request: schemas.OTPRequest, db: Session = Depends(get_db)):
    identifier = request.email.strip().replace(" ", "")
    if not identifier:
        raise HTTPException(status_code=400, detail="Invalid email format" if "@" in request.email else "Invalid phone format")

    is_phone = identifier.replace("+", "").isdigit()
    if is_phone:
        if not identifier.startswith("+"):
            if len(identifier) == 10:
                identifier = f"+91{identifier}"
            else:
                raise HTTPException(status_code=400, detail="Invalid phone format")
    else:
        if " " in request.email or identifier.endswith("gmail.con") or identifier.endswith("gmail,com") or "@" not in identifier:
            raise HTTPException(status_code=400, detail="Invalid email format")
    
    # 1. Automatic cleanup of expired OTP records for this user to prevent database pollution
    try:
        expired_count = db.query(models.OTPCode).filter(
            (models.OTPCode.email_or_phone == identifier) & (models.OTPCode.expires_at < datetime.utcnow())
        ).delete()
        if expired_count > 0:
            db.commit()
            logger.info(f"[OTP Cleanup] Removed {expired_count} expired OTP records for {identifier}")
    except Exception as cleanup_err:
        logger.error(f"[OTP Cleanup Error]: {cleanup_err}")
        db.rollback()

    db_otp = db.query(models.OTPCode).filter(models.OTPCode.email_or_phone == identifier).first()
    
    # 2. Check 30s cooldown only if db_otp exists and has last_sent_at set.
    if db_otp and db_otp.last_sent_at:
        time_elapsed = (datetime.utcnow() - db_otp.last_sent_at).total_seconds()
        if time_elapsed < 30:
            retry_after = int(30 - time_elapsed)
            logger.warning(f"[OTP Cooldown Blocked] {identifier} requested OTP again in {time_elapsed:.1f}s. Cooldown active for {retry_after}s.")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Please wait {retry_after} seconds before requesting a new OTP."
            )

    otp = str(random.randint(100000, 999999))
    expiry = datetime.utcnow() + timedelta(minutes=5)
    
    # Prepare update/insert but do not commit yet.
    if db_otp:
        db_otp.otp_code = otp
        db_otp.expires_at = expiry
        db_otp.verified = False
        db_otp.attempts = 0
        db_otp.last_sent_at = datetime.utcnow()
    else:
        db_otp = models.OTPCode(
            email_or_phone=identifier,
            otp_code=otp,
            expires_at=expiry,
            last_sent_at=datetime.utcnow()
        )
        db.add(db_otp)
    
    is_dev = os.getenv("ENV", "production") == "development"
    logger.info(f"[OTP Request] Generated OTP for {identifier} (Is Phone: {is_phone}, Env: {os.getenv('ENV', 'production')})")

    if is_phone:
        sent = auth_utils.send_otp_sms(identifier, otp)
        if not sent:
            logger.error(f"[OTP SMS Error] Failed to send SMS via Twilio to {identifier}")
            db.rollback()
            raise HTTPException(status_code=500, detail="Failed to send SMS verification code.")
        db.commit()
        logger.info(f"[OTP SMS Success] OTP code sent successfully to {identifier}")
        return {"message": "Verification code sent successfully", "identifier": identifier}
    else:
        # Email OTP sending
        try:
            success, is_mock = auth_utils.send_otp_email(identifier, otp)
        except Exception as email_err:
            logger.error(f"[OTP Email Error] Exception occurred while sending email to {identifier}: {email_err}")
            success, is_mock = False, False

        if not success:
            if is_dev:
                # In development mode, fallback to dev_otp
                logger.info(f"[OTP Email Dev Fallback] Email sending failed, but running in development mode. Returning dev_otp: {otp}")
                db.commit()
                return {
                    "message": "Verification code generated (dev fallback)",
                    "identifier": identifier,
                    "dev_otp": otp
                }
            else:
                # In production, do not commit. Rollback so cooldown isn't registered for failed attempts.
                logger.error(f"[OTP Email Error] Failed to deliver email to {identifier} in production.")
                db.rollback()
                raise HTTPException(
                    status_code=500,
                    detail="Failed to send verification email. Please check your email address or try again later."
                )

        db.commit()
        logger.info(f"[OTP Email Success] Email sent successfully to {identifier} (Is Mock: {is_mock})")
        response = {"message": "Verification code sent successfully", "identifier": identifier}
        if is_mock:
            response["dev_otp"] = otp
        return response

@router.post("/verify-otp")
def verify_otp(request: schemas.OTPVerify, db: Session = Depends(get_db)):
    identifier = request.email.strip().replace(" ", "")
    is_phone = identifier.replace("+", "").isdigit()
    logger.info(f"[OTP Verification Request] Verifying OTP for {identifier} (Is Phone: {is_phone})")

    if is_phone:
        if not identifier.startswith("+") and len(identifier) == 10:
            identifier = f"+91{identifier}"
            
        verified = auth_utils.verify_twilio_otp(identifier, request.otp)
        if not verified:
            db_otp = db.query(models.OTPCode).filter(models.OTPCode.email_or_phone == identifier).first()
            if not db_otp:
                logger.error(f"[OTP Verification Failed] No custom OTP record found for {identifier}")
                raise HTTPException(status_code=400, detail="No OTP requested for this phone number")
            
            if db_otp.otp_code != request.otp or datetime.utcnow() > db_otp.expires_at:
                logger.error(f"[OTP Verification Failed] Custom OTP code invalid or expired for {identifier}")
                raise HTTPException(status_code=400, detail="Invalid or expired OTP code")
            db_otp.verified = True
            db.commit()
            logger.info(f"[OTP Verification Success] Phone custom OTP verified successfully for {identifier}")
        else:
            db_otp = db.query(models.OTPCode).filter(models.OTPCode.email_or_phone == identifier).first()
            if db_otp:
                db_otp.verified = True
                db.commit()
            logger.info(f"[OTP Verification Success] Phone Twilio OTP verified successfully for {identifier}")
    else:
        db_otp = db.query(models.OTPCode).filter(models.OTPCode.email_or_phone == identifier).first()
        if not db_otp:
            logger.error(f"[OTP Verification Failed] No OTP record found in database for {identifier}")
            raise HTTPException(status_code=400, detail="No OTP requested for this email address.")
        
        if db_otp.attempts >= 5:
            logger.error(f"[OTP Verification Failed] {identifier} exceeded max verification attempts.")
            db.delete(db_otp)
            db.commit()
            raise HTTPException(status_code=400, detail="Too many failed attempts. Please request a new OTP.")
        
        if db_otp.otp_code != request.otp:
            db_otp.attempts += 1
            db.commit()
            remaining = 5 - db_otp.attempts
            logger.error(f"[OTP Verification Failed] Invalid OTP entered for {identifier}. Remaining attempts: {remaining}")
            raise HTTPException(status_code=400, detail=f"Invalid OTP code. You have {remaining} attempts remaining.")
        
        if datetime.utcnow() > db_otp.expires_at:
            logger.error(f"[OTP Verification Failed] OTP code expired for {identifier} (Expired at {db_otp.expires_at})")
            db.delete(db_otp)
            db.commit()
            raise HTTPException(status_code=400, detail="OTP code has expired. Please request a new one.")
        
        db_otp.verified = True
        db.commit()
        logger.info(f"[OTP Verification Success] Email OTP verified successfully for {identifier}")
    
    # Check if user exists
    user = db.query(models.User).filter(
        (models.User.email == identifier) | (models.User.phone == identifier) | (models.User.email == f"{identifier}@agrinex.local")
    ).first()
        
    if user:
        access_token = auth_utils.create_access_token(data={"sub": user.email})
        # Cleanup verified OTP code
        db_otp = db.query(models.OTPCode).filter(models.OTPCode.email_or_phone == identifier).first()
        if db_otp:
            db.delete(db_otp)
            db.commit()
        logger.info(f"[OTP Verification Complete] User {identifier} logged in via OTP.")
        return {
            "message": "OTP verified successfully",
            "access_token": access_token,
            "token_type": "bearer",
            "user": user
        }
    
    logger.info(f"[OTP Verification Complete] {identifier} verified, ready for registration/signup.")
    return {"message": "OTP verified successfully", "identifier": identifier}

@router.post("/check-account")
def check_account(request: schemas.CheckAccountRequest, db: Session = Depends(get_db)):
    target = request.identifier.strip().replace(" ", "")
    user = db.query(models.User).filter(
        (models.User.email == target) | (models.User.phone == target) | (models.User.email == f"{target}@agrinex.local")
    ).first()
    if user:
        return {"exists": True, "message": "Account already exists. Please login."}
    return {"exists": False}

@router.post("/register")
def register(request: schemas.RegisterRequest, db: Session = Depends(get_db)):
    conditions = []
    if request.email and request.email.strip():
        conditions.append(models.User.email == request.email.strip())
    if request.phone and request.phone.strip():
        conditions.append(models.User.phone == request.phone.strip())
    
    if conditions:
        from sqlalchemy import or_
        existing_user = db.query(models.User).filter(or_(*conditions)).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Account already exists. Please login.")
    
    identifier = request.email.strip() if request.email.strip() else request.phone.strip()
    db_otp = db.query(models.OTPCode).filter(
        models.OTPCode.email_or_phone == identifier,
        models.OTPCode.verified == True
    ).first()
    
    if not db_otp:
        raise HTTPException(status_code=400, detail="Please verify your identifier via OTP first")
    
    final_email = request.email.strip() if request.email.strip() else f"{request.phone.strip()}@agrinex.local"
    final_phone = request.phone.strip() if request.phone.strip() else None

    new_user = models.User(
        email=final_email,
        phone=final_phone,
        full_name=request.full_name,
        is_verified=True
    )
    
    db.add(new_user)
    db.delete(db_otp)
    db.commit()
    db.refresh(new_user)
    
    return {
        "message": "Information saved. Please set your password.",
        "user": new_user
    }

@router.post("/signup")
def signup(request: schemas.RegisterRequest, db: Session = Depends(get_db)):
    return register(request, db)

@router.post("/google", response_model=schemas.Token)
def google_login(request: schemas.GoogleLoginRequest, db: Session = Depends(get_db)):
    email = request.profile.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Google profile missing email")
    
    user = db.query(models.User).filter(models.User.email == email).first()
    is_new = False
    if not user:
        is_new = True
        full_name = request.profile.get("name", "Google User")
        picture = request.profile.get("picture")
        user = models.User(
            email=email,
            full_name=full_name,
            profile_picture=picture,
            is_verified=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    
    access_token = auth_utils.create_access_token(data={"sub": user.email})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
        "is_new": is_new
    }

@router.post("/set-password", response_model=schemas.Token)
def set_password(request: schemas.PasswordSetRequest, db: Session = Depends(get_db)):
    target = request.email.strip()
    user = db.query(models.User).filter(
        (models.User.email == target) | (models.User.phone == target) | (models.User.email == f"{target}@agrinex.local")
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.hashed_password = auth_utils.get_password_hash(request.password)
    db.commit()
    db.refresh(user)
    
    access_token = auth_utils.create_access_token(data={"sub": user.email})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
        "is_new": True
    }

@router.post("/login", response_model=schemas.Token)
def login(request: schemas.LoginRequest, db: Session = Depends(get_db)):
    target = request.email.strip()
    user = db.query(models.User).filter(
        (models.User.email == target) | (models.User.phone == target) | (models.User.email == f"{target}@agrinex.local")
    ).first()
        
    if not user:
        raise HTTPException(status_code=401, detail="Email not registered")
    
    if not auth_utils.verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    access_token = auth_utils.create_access_token(data={"sub": user.email})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }

@router.post("/forgot-password")
def forgot_password(request: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    target = request.email.strip().replace(" ", "")
    if not target:
        raise HTTPException(status_code=400, detail="Invalid email format" if "@" in request.email else "Invalid phone format")

    is_phone = target.replace("+", "").isdigit()
    if is_phone:
        if not target.startswith("+"):
            if len(target) == 10:
                target = f"+91{target}"
            else:
                raise HTTPException(status_code=400, detail="Invalid phone format")
    else:
        if " " in request.email or target.endswith("gmail.con") or target.endswith("gmail,com") or "@" not in target:
            raise HTTPException(status_code=400, detail="Invalid email format")

    user = db.query(models.User).filter(
        (models.User.email == target) | (models.User.phone == target) | (models.User.email == f"{target}@agrinex.local")
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Phone not registered" if is_phone else "Email not registered")
    
    otp = str(random.randint(100000, 999999))
    expiry = datetime.utcnow() + timedelta(minutes=5)
    
    db_otp = db.query(models.OTPCode).filter(models.OTPCode.email_or_phone == target).first()
    if db_otp:
        db_otp.otp_code = otp
        db_otp.expires_at = expiry
        db_otp.verified = False
        db_otp.attempts = 0
        db_otp.last_sent_at = datetime.utcnow()
    else:
        db_otp = models.OTPCode(email_or_phone=target, otp_code=otp, expires_at=expiry, last_sent_at=datetime.utcnow())
        db.add(db_otp)
    db.commit()
    
    if is_phone:
        sent = auth_utils.send_otp_sms(target, otp)
        if not sent:
            raise HTTPException(status_code=500, detail="OTP provider failed")
        return {"message": "Verification code sent successfully", "identifier": target}
    else:
        result = auth_utils.send_otp_email(target, otp)
        success, is_mock = result if isinstance(result, tuple) else (result, False)
        if not success:
            raise HTTPException(status_code=500, detail="OTP provider failed")
        response = {"message": "Verification code sent successfully", "identifier": target}
        if is_mock:
            response["dev_otp"] = otp
        return response

@router.post("/reset-password")
def reset_password(request: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    target = request.email.strip()
    db_otp = db.query(models.OTPCode).filter(
        models.OTPCode.email_or_phone == target,
        models.OTPCode.otp_code == request.otp,
        models.OTPCode.expires_at > datetime.utcnow()
    ).first()
    
    if not db_otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    
    user = db.query(models.User).filter(
        (models.User.email == target) | (models.User.phone == target) | (models.User.email == f"{target}@agrinex.local")
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.hashed_password = auth_utils.get_password_hash(request.new_password)
    db.delete(db_otp)
    db.commit()
    
    return {"message": "Password reset successfully"}

@router.post("/refresh")
def refresh_token(request: schemas.RefreshTokenRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    payload = auth_utils.verify_token(request.refresh_token, expected_type="refresh")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )
    
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    new_access_token = auth_utils.create_access_token(data={"sub": user.email})
    new_refresh_token = auth_utils.create_refresh_token(data={"sub": user.email})
    
    logger.info(f"[Token Refresh] Tokens refreshed for {user.email}")
    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }
