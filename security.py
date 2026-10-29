import os
import re
import secrets
import smtplib
import unicodedata
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr

import bcrypt
from dotenv import load_dotenv

from database import EmailOTP

load_dotenv()

EMAIL_PATTERN = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"


class ValidationError(ValueError):
    """Raised when registration or OTP validation fails."""


def _clean_text(value, field_name, min_length=1, max_length=120):
    if value is None:
        raise ValidationError(f"{field_name} ನಮೂದಿಸಿ.")
    value = unicodedata.normalize("NFKC", str(value)).strip()
    value = re.sub(r"\s+", " ", value)
    if len(value) < min_length:
        raise ValidationError(f"{field_name} ಕನಿಷ್ಠ {min_length} ಅಕ್ಷರಗಳಿರಬೇಕು.")
    if len(value) > max_length:
        raise ValidationError(f"{field_name} ಗರಿಷ್ಠ {max_length} ಅಕ್ಷರಗಳಿರಬಹುದು.")
    if any(unicodedata.category(ch) == "Cc" for ch in value):
        raise ValidationError(f"{field_name} ನಲ್ಲಿ ಅನಗತ್ಯ ಅಕ್ಷರಗಳಿವೆ.")
    return value


def validate_registration(data):
    """Validate registration fields. Address and village are optional."""
    if not isinstance(data, dict):
        raise ValidationError("Registration details ಸರಿಯಾಗಿ ಬಂದಿಲ್ಲ.")

    full_name = _clean_text(data.get("full_name"), "ಹೆಸರು", 2, 100)
    if not any(ch.isalpha() for ch in full_name):
        raise ValidationError("ಸರಿಯಾದ ಹೆಸರನ್ನು ನಮೂದಿಸಿ.")

    email = str(data.get("email", "")).strip().lower()
    if len(email) > 254 or not re.fullmatch(EMAIL_PATTERN, email):
        raise ValidationError("ಸರಿಯಾದ Email address ನಮೂದಿಸಿ.")

    phone = re.sub(r"[\s-]", "", str(data.get("phone", "")).strip())
    if phone.startswith("+91"):
        phone = phone[3:]
    elif phone.startswith("91") and len(phone) == 12:
        phone = phone[2:]
    if not re.fullmatch(r"[6-9]\d{9}", phone):
        raise ValidationError("ಸರಿಯಾದ 10 ಅಂಕಿಗಳ ಭಾರತೀಯ ಮೊಬೈಲ್ ಸಂಖ್ಯೆಯನ್ನು ನಮೂದಿಸಿ.")

    username = str(data.get("username", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{4,30}", username):
        raise ValidationError("Username 4–30 characters ಇರಬೇಕು; English letters, numbers ಮತ್ತು underscore ಮಾತ್ರ ಬಳಸಿ.")

    password = data.get("password", "")
    confirm_password = data.get("confirm_password", data.get("confirm", ""))
    if not isinstance(password, str) or not 8 <= len(password) <= 72:
        raise ValidationError("Password 8–72 characters ಇರಬೇಕು.")
    if len(password.encode("utf-8")) > 72:
        raise ValidationError("Password ತುಂಬಾ ಉದ್ದವಾಗಿದೆ.")
    if not re.search(r"[A-Z]", password):
        raise ValidationError("Password ನಲ್ಲಿ ಕನಿಷ್ಠ ಒಂದು uppercase English letter ಇರಬೇಕು.")
    if not re.search(r"[a-z]", password):
        raise ValidationError("Password ನಲ್ಲಿ ಕನಿಷ್ಠ ಒಂದು lowercase English letter ಇರಬೇಕು.")
    if not re.search(r"\d", password):
        raise ValidationError("Password ನಲ್ಲಿ ಕನಿಷ್ಠ ಒಂದು ಸಂಖ್ಯೆ ಇರಬೇಕು.")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValidationError("Password ನಲ್ಲಿ ಕನಿಷ್ಠ ಒಂದು special character ಇರಬೇಕು.")
    if password != confirm_password:
        raise ValidationError("ಎರಡೂ Password ಒಂದೇ ಆಗಿರಬೇಕು.")

    return {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "username": username,
        "address": str(data.get("address") or "").strip()[:255],
        "village": str(data.get("village") or "").strip()[:100],
        "password": password,
    }


def validate_new_password(password, confirm_password):
    """Same password rules as registration. Used by Forgot Password."""
    if not isinstance(password, str) or not 8 <= len(password) <= 72:
        raise ValidationError("Password 8–72 characters ಇರಬೇಕು.")
    if len(password.encode("utf-8")) > 72:
        raise ValidationError("Password ತುಂಬಾ ಉದ್ದವಾಗಿದೆ.")
    if not re.search(r"[A-Z]", password):
        raise ValidationError("Password ನಲ್ಲಿ ಕನಿಷ್ಠ ಒಂದು uppercase English letter ಇರಬೇಕು.")
    if not re.search(r"[a-z]", password):
        raise ValidationError("Password ನಲ್ಲಿ ಕನಿಷ್ಠ ಒಂದು lowercase English letter ಇರಬೇಕು.")
    if not re.search(r"\d", password):
        raise ValidationError("Password ನಲ್ಲಿ ಕನಿಷ್ಠ ಒಂದು ಸಂಖ್ಯೆ ಇರಬೇಕು.")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValidationError("Password ನಲ್ಲಿ ಕನಿಷ್ಠ ಒಂದು special character ಇರಬೇಕು.")
    if password != confirm_password:
        raise ValidationError("ಎರಡೂ Password ಒಂದೇ ಆಗಿರಬೇಕು.")
    return True


def hash_password(password):
    if not isinstance(password, str) or not password:
        raise ValidationError("Password ಖಾಲಿಯಾಗಿರಬಾರದು.")
    encoded = password.encode("utf-8")
    if len(encoded) > 72:
        raise ValidationError("Password ತುಂಬಾ ಉದ್ದವಾಗಿದೆ.")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password, password_hash):
    if not isinstance(password, str) or not isinstance(password_hash, str):
        return False
    try:
        encoded = password.encode("utf-8")
        if len(encoded) > 72:
            return False
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except (ValueError, TypeError, UnicodeError):
        return False


def _otp_hash(code):
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _otp_email_html(code, recipient_email, purpose="register"):
    """Responsive, professional HTML email for account verification / password reset."""
    if purpose == "reset":
        mail_title = "Reset your password"
        mail_intro = "Use the one-time password below to reset the password of your account"
        mail_ignore = "If you did not request a password reset, you can safely ignore this email. Your password will not change."
    else:
        mail_title = "Verify your email address"
        mail_intro = "Use the verification code below to complete your account registration for"
        mail_ignore = "If you did not request this verification, you can safely ignore this email."
    safe_email = recipient_email.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f3f7f2;font-family:Arial,Helvetica,sans-serif;color:#1f2937;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f7f2;padding:28px 12px;"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid #e2eadf;border-radius:18px;overflow:hidden;">
<tr><td style="padding:26px 30px;background:#176b38;color:#ffffff;">
<div style="font-size:13px;letter-spacing:1.4px;text-transform:uppercase;opacity:.9;">Krishi Equipment</div>
<div style="font-size:25px;font-weight:700;margin-top:9px;line-height:1.3;">{mail_title}</div>
<div style="font-size:14px;line-height:1.6;margin-top:8px;color:#e5f4e6;">Farm equipment booking &amp; billing platform</div>
</td></tr>
<tr><td style="padding:30px;">
<p style="font-size:16px;line-height:1.7;margin:0 0 14px;">Hello,</p>
<p style="font-size:15px;line-height:1.7;margin:0 0 20px;">{mail_intro} <strong>{safe_email}</strong>.</p>
<div style="background:#f3f8f1;border:1px solid #dcebd7;border-radius:14px;padding:22px 16px;text-align:center;">
<div style="font-size:12px;color:#55705a;letter-spacing:1.8px;text-transform:uppercase;">Your one-time password</div>
<div style="font-size:34px;letter-spacing:8px;font-weight:800;color:#176b38;margin-top:12px;">{code}</div>
<div style="font-size:13px;color:#64748b;margin-top:12px;">Valid for 10 minutes</div>
</div>
<p style="font-size:14px;line-height:1.7;margin:22px 0 0;">For your security, never share this code with anyone. Our team will never ask you to disclose your OTP.</p>
<p style="font-size:14px;line-height:1.7;margin:14px 0 0;">{mail_ignore}</p>
</td></tr>
<tr><td style="padding:18px 30px;background:#f8faf8;border-top:1px solid #edf1eb;color:#718071;font-size:12px;line-height:1.6;">This is an automated message from Krishi Equipment. Please do not reply to this email.</td></tr>
</table><div style="font-size:11px;color:#8a978a;margin-top:16px;">Reliable tools for better farm planning.</div>
</td></tr></table></body></html>'''


def send_otp(email, db, purpose="register"):
    email = str(email).strip().lower()
    if not re.fullmatch(EMAIL_PATTERN, email):
        raise ValidationError("ಸರಿಯಾದ Email address ನಮೂದಿಸಿ.")

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError as exc:
        raise ValidationError("SMTP_PORT ಸರಿಯಾದ ಸಂಖ್ಯೆಯಾಗಿರಬೇಕು.") from exc
    smtp_username = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from = os.getenv("SMTP_FROM", smtp_username).strip()
    smtp_from_name = os.getenv("SMTP_FROM_NAME", "Krishi Equipment").strip()

    if not smtp_username or not smtp_password or not smtp_from:
        raise ValidationError(".env ನಲ್ಲಿ SMTP_USERNAME, SMTP_PASSWORD ಮತ್ತು SMTP_FROM ಹೊಂದಿಸಿ.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        db.query(EmailOTP).filter(EmailOTP.email == email).delete(synchronize_session=False)
        # The database model uses code_hash (not otp_hash).
        otp_record = EmailOTP(
            email=email,
            code_hash=_otp_hash(code),
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            attempts=0,
        )
        db.add(otp_record)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise ValidationError("OTP ದಾಖಲಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ. email_otps database columns ಪರಿಶೀಲಿಸಿ.") from exc

    message = EmailMessage()
    message["Subject"] = ("Reset your password | Krishi Equipment" if purpose == "reset"
                          else "Verify your email | Krishi Equipment")
    message["From"] = formataddr((smtp_from_name, smtp_from))
    message["To"] = email
    if purpose == "reset":
        message.set_content(
            f"Krishi Equipment password reset\n\nYour one-time password is: {code}\n"
            "This code expires in 10 minutes. Never share it with anyone.\n"
            "If you did not request this, you can ignore this email."
        )
    else:
        message.set_content(
            f"Krishi Equipment email verification\n\nYour verification code is: {code}\n"
            "This code expires in 10 minutes. Never share it with anyone.\n"
            "If you did not request this, you can ignore this email."
        )
    message.add_alternative(_otp_email_html(code, email, purpose), subtype="html")

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=25) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_username, smtp_password)
            server.send_message(message)
    except Exception as exc:
        try:
            db.delete(otp_record)
            db.commit()
        except Exception:
            db.rollback()
        raise ValidationError("OTP email ಕಳುಹಿಸಲಾಗಲಿಲ್ಲ. SMTP settings ಮತ್ತು App Password ಪರಿಶೀಲಿಸಿ.") from exc
    return True


def verify_otp(email, code, db):
    email = str(email).strip().lower()
    code = str(code).strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValidationError("6 ಅಂಕಿಗಳ OTP ನಮೂದಿಸಿ.")

    otp_record = (
        db.query(EmailOTP)
        .filter(EmailOTP.email == email)
        .order_by(EmailOTP.id.desc())
        .first()
    )
    if otp_record is None:
        raise ValidationError("OTP ಸಿಗಲಿಲ್ಲ. ಹೊಸ OTP ಪಡೆಯಿರಿ.")

    if otp_record.expires_at < datetime.utcnow():
        db.delete(otp_record)
        db.commit()
        raise ValidationError("OTP ಅವಧಿ ಮುಗಿದಿದೆ. ಹೊಸ OTP ಪಡೆಯಿರಿ.")

    if otp_record.attempts >= 5:
        db.delete(otp_record)
        db.commit()
        raise ValidationError("ತಪ್ಪು OTP ಪ್ರಯತ್ನಗಳು ಹೆಚ್ಚಾಗಿವೆ. ಹೊಸ OTP ಪಡೆಯಿರಿ.")

    otp_record.attempts += 1
    try:
        valid = bcrypt.checkpw(code.encode("utf-8"), otp_record.code_hash.encode("utf-8"))
    except (ValueError, TypeError, AttributeError):
        db.rollback()
        raise ValidationError("OTP ಪರಿಶೀಲಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ. ಹೊಸ OTP ಪಡೆಯಿರಿ.")

    if not valid:
        if otp_record.attempts >= 5:
            db.delete(otp_record)
        db.commit()
        raise ValidationError("OTP ತಪ್ಪಾಗಿದೆ. ಮತ್ತೊಮ್ಮೆ ಪರಿಶೀಲಿಸಿ.")

    db.delete(otp_record)
    db.commit()
    return True
