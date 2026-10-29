"""Booking e-mail notifications for Krishi Equipment.

Sends a professional HTML e-mail (with a plain-text fallback and an
"Add to calendar" .ics attachment) to the e-mail address the farmer entered
during registration.

Uses the SAME .env settings as the OTP mail:
    SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM, SMTP_FROM_NAME
Optional:
    APP_NAME          - brand shown in the mail (default "Krishi Equipment")
    APP_PUBLIC_URL    - if set, a "View my bookings" button is added to the mail

Public functions (they NEVER raise - a mail problem must not undo a booking):
    send_booking_confirmation(booking_id) -> (ok: bool, message: str)
    send_booking_cancellation(booking_id) -> (ok: bool, message: str)
"""
import html
import os
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr

from dotenv import load_dotenv
from sqlalchemy.orm import joinedload

from database import SessionLocal, Booking

load_dotenv()

BRAND = os.getenv("APP_NAME", "Krishi Equipment").strip() or "Krishi Equipment"

# ---------------------------------------------------------------------------
# Small translation table (farmer's preferred_language: English / Kannada / Hindi)
# ---------------------------------------------------------------------------
T = {
    "English": {
        "c_subject": "Booking confirmed",
        "c_title": "Your booking is confirmed",
        "c_intro": "Thank you for booking with us. Your equipment is reserved for the slot below.",
        "x_subject": "Booking cancelled",
        "x_title": "Your booking was cancelled",
        "x_intro": "The booking below has been cancelled. The slot is now free for others.",
        "hello": "Hello",
        "booking_id": "Booking ID", "equipment": "Equipment", "equip_id": "Equipment ID",
        "date": "Date", "time": "Time", "duration": "Duration", "rate": "Hourly rate",
        "estimate": "Estimated cost", "location": "Equipment location", "contact": "Owner contact",
        "notes": "Your notes", "status": "Status", "booked_on": "Booked on",
        "hours": "hour(s)", "next": "What happens next",
        "n1": "Reach the work site a few minutes before your start time.",
        "n2": "Final bill = hours actually used × hourly rate. It is prepared after the work.",
        "n3": "You can cancel or view this booking anytime from 'My Bookings' in the app.",
        "estimate_note": "Estimate only - the final bill depends on the hours actually used.",
        "cal": "Add to calendar: open the attached .ics file.",
        "view": "View my bookings",
        "auto": "This is an automated message. Please do not reply to this email.",
        "tagline": "Reliable tools for better farm planning.",
    },
    "Kannada": {
        "c_subject": "ಬುಕ್ಕಿಂಗ್ ದೃಢಪಟ್ಟಿದೆ",
        "c_title": "ನಿಮ್ಮ ಬುಕ್ಕಿಂಗ್ ದೃಢಪಟ್ಟಿದೆ",
        "c_intro": "ಬುಕ್ ಮಾಡಿದ್ದಕ್ಕೆ ಧನ್ಯವಾದಗಳು. ಕೆಳಗಿನ ಸಮಯಕ್ಕೆ ನಿಮ್ಮ ಯಂತ್ರ ಕಾಯ್ದಿರಿಸಲಾಗಿದೆ.",
        "x_subject": "ಬುಕ್ಕಿಂಗ್ ರದ್ದಾಗಿದೆ",
        "x_title": "ನಿಮ್ಮ ಬುಕ್ಕಿಂಗ್ ರದ್ದಾಗಿದೆ",
        "x_intro": "ಕೆಳಗಿನ ಬುಕ್ಕಿಂಗ್ ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ. ಈ ಸಮಯ ಈಗ ಇತರರಿಗೆ ಲಭ್ಯ.",
        "hello": "ನಮಸ್ಕಾರ",
        "booking_id": "ಬುಕ್ಕಿಂಗ್ ಸಂಖ್ಯೆ", "equipment": "ಯಂತ್ರ", "equip_id": "ಯಂತ್ರ ಐಡಿ",
        "date": "ದಿನಾಂಕ", "time": "ಸಮಯ", "duration": "ಅವಧಿ", "rate": "ಗಂಟೆಯ ದರ",
        "estimate": "ಅಂದಾಜು ವೆಚ್ಚ", "location": "ಯಂತ್ರದ ಸ್ಥಳ", "contact": "ಮಾಲೀಕರ ಸಂಪರ್ಕ",
        "notes": "ನಿಮ್ಮ ಟಿಪ್ಪಣಿ", "status": "ಸ್ಥಿತಿ", "booked_on": "ಬುಕ್ ಮಾಡಿದ ದಿನ",
        "hours": "ಗಂಟೆ", "next": "ಮುಂದೇನು",
        "n1": "ಆರಂಭ ಸಮಯಕ್ಕಿಂತ ಕೆಲವು ನಿಮಿಷ ಮೊದಲು ಕೆಲಸದ ಸ್ಥಳಕ್ಕೆ ಬನ್ನಿ.",
        "n2": "ಅಂತಿಮ ಬಿಲ್ = ಬಳಸಿದ ಗಂಟೆ × ಗಂಟೆಯ ದರ. ಕೆಲಸದ ನಂತರ ಬಿಲ್ ಸಿದ್ಧವಾಗುತ್ತದೆ.",
        "n3": "ಆ್ಯಪ್‌ನ 'ನನ್ನ ಬುಕ್ಕಿಂಗ್‌ಗಳು' ಭಾಗದಲ್ಲಿ ಯಾವಾಗ ಬೇಕಾದರೂ ನೋಡಬಹುದು ಅಥವಾ ರದ್ದು ಮಾಡಬಹುದು.",
        "estimate_note": "ಇದು ಅಂದಾಜು ಮಾತ್ರ - ಅಂತಿಮ ಬಿಲ್ ನಿಜವಾಗಿ ಬಳಸಿದ ಗಂಟೆಯ ಮೇಲೆ ಅವಲಂಬಿತ.",
        "cal": "ಕ್ಯಾಲೆಂಡರ್‌ಗೆ ಸೇರಿಸಲು ಲಗತ್ತಿಸಿದ .ics ಫೈಲ್ ತೆರೆಯಿರಿ.",
        "view": "ನನ್ನ ಬುಕ್ಕಿಂಗ್‌ಗಳನ್ನು ನೋಡಿ",
        "auto": "ಇದು ಸ್ವಯಂಚಾಲಿತ ಸಂದೇಶ. ದಯವಿಟ್ಟು ಈ ಇಮೇಲ್‌ಗೆ ಉತ್ತರಿಸಬೇಡಿ.",
        "tagline": "ಉತ್ತಮ ಕೃಷಿ ಯೋಜನೆಗೆ ನಂಬಿಕಸ್ಥ ಸಾಧನಗಳು.",
    },
    "Hindi": {
        "c_subject": "बुकिंग पक्की हो गई",
        "c_title": "आपकी बुकिंग पक्की हो गई है",
        "c_intro": "बुकिंग के लिए धन्यवाद। नीचे दिए समय के लिए आपका उपकरण आरक्षित है।",
        "x_subject": "बुकिंग रद्द हुई",
        "x_title": "आपकी बुकिंग रद्द हो गई है",
        "x_intro": "नीचे दी गई बुकिंग रद्द कर दी गई है। यह समय अब दूसरों के लिए उपलब्ध है।",
        "hello": "नमस्ते",
        "booking_id": "बुकिंग नंबर", "equipment": "उपकरण", "equip_id": "उपकरण आईडी",
        "date": "तारीख", "time": "समय", "duration": "अवधि", "rate": "प्रति घंटा दर",
        "estimate": "अनुमानित लागत", "location": "उपकरण का स्थान", "contact": "मालिक का संपर्क",
        "notes": "आपके नोट्स", "status": "स्थिति", "booked_on": "बुकिंग की तारीख",
        "hours": "घंटे", "next": "आगे क्या होगा",
        "n1": "शुरू होने के समय से कुछ मिनट पहले कार्यस्थल पर पहुंचें।",
        "n2": "अंतिम बिल = वास्तव में उपयोग किए घंटे × प्रति घंटा दर। बिल काम के बाद बनता है।",
        "n3": "ऐप के 'मेरी बुकिंग' में आप कभी भी इसे देख या रद्द कर सकते हैं।",
        "estimate_note": "यह केवल अनुमान है - अंतिम बिल वास्तविक उपयोग के घंटों पर निर्भर है।",
        "cal": "कैलेंडर में जोड़ने के लिए संलग्न .ics फ़ाइल खोलें।",
        "view": "मेरी बुकिंग देखें",
        "auto": "यह स्वचालित संदेश है। कृपया इस ईमेल का उत्तर न दें।",
        "tagline": "बेहतर खेती की योजना के लिए भरोसेमंद साधन।",
    },
}


def _esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def _money(value):
    try:
        return f"₹{float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "₹0.00"


def _smtp_settings():
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        raise RuntimeError("SMTP_PORT must be a number.")
    user = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    sender = os.getenv("SMTP_FROM", user).strip()
    name = os.getenv("SMTP_FROM_NAME", BRAND).strip() or BRAND
    if not user or not password or not sender:
        raise RuntimeError("SMTP_USERNAME, SMTP_PASSWORD and SMTP_FROM are not set in .env.")
    return host, port, user, password, sender, name


def _load(booking_id):
    """Read everything the mail needs and return a plain dict (no live ORM objects)."""
    with SessionLocal() as db:
        b = (db.query(Booking)
             .options(joinedload(Booking.machine), joinedload(Booking.farmer))
             .filter(Booking.id == int(booking_id)).first())
        if b is None:
            raise RuntimeError("Booking not found.")
        if b.farmer is None or not (b.farmer.email or "").strip():
            raise RuntimeError("The farmer has no e-mail address on file.")
        m, f = b.machine, b.farmer
        start = datetime.combine(b.booking_date, b.start_time)
        end = start + timedelta(hours=int(b.booked_hours))
        rate = float(m.hourly_rate or 0) if m else 0.0
        return {
            "booking_id": b.id, "status": b.status, "notes": (b.notes or "").strip(),
            "created_at": b.created_at, "start": start, "end": end, "hours": int(b.booked_hours),
            "machine_name": m.name if m else "", "machine_code": (m.machine_code or f"KE-{m.id:06d}") if m else "",
            "machine_location": (m.location or "").strip() if m else "",
            "machine_phone": (m.contact_phone or "").strip() if m else "",
            "rate": rate, "estimate": rate * int(b.booked_hours),
            "farmer_name": f.full_name, "farmer_email": f.email.strip(),
            "lang": f.preferred_language if f.preferred_language in T else "English",
        }


def _ics(d, cancelled=False):
    """Minimal RFC 5545 calendar file so the farmer can add the slot to any calendar app."""
    def esc(s):
        return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    fmt = "%Y%m%dT%H%M%S"
    desc = f"{d['machine_name']} ({d['machine_code']}) - Booking #{d['booking_id']}"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//{BRAND}//Booking//EN",
        "METHOD:CANCEL" if cancelled else "METHOD:PUBLISH", "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT", f"UID:booking-{d['booking_id']}@krishi-equipment",
        f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{d['start'].strftime(fmt)}", f"DTEND:{d['end'].strftime(fmt)}",
        f"SUMMARY:{esc(d['machine_name'] + ' booking')}",
        f"DESCRIPTION:{esc(desc)}",
    ]
    if d["machine_location"]:
        lines.append(f"LOCATION:{esc(d['machine_location'])}")
    lines += ["STATUS:CANCELLED" if cancelled else "STATUS:CONFIRMED", "SEQUENCE:1" if cancelled else "SEQUENCE:0",
              "BEGIN:VALARM", "TRIGGER:-PT60M", "ACTION:DISPLAY", f"DESCRIPTION:{esc(d['machine_name'])} in 1 hour",
              "END:VALARM", "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def _rows(d, t, cancelled):
    rows = [
        (t["booking_id"], f"#{d['booking_id']}"),
        (t["equipment"], f"{d['machine_name']}"),
        (t["equip_id"], d["machine_code"]),
        (t["date"], d["start"].strftime("%A, %d %B %Y")),
        (t["time"], f"{d['start']:%H:%M} – {d['end']:%H:%M}"),
        (t["duration"], f"{d['hours']} {t['hours']}"),
        (t["rate"], f"{_money(d['rate'])} / hr"),
    ]
    if not cancelled:
        rows.append((t["estimate"], _money(d["estimate"])))
    if d["machine_location"]:
        rows.append((t["location"], d["machine_location"]))
    if d["machine_phone"]:
        rows.append((t["contact"], d["machine_phone"]))
    if d["notes"]:
        rows.append((t["notes"], d["notes"]))
    rows.append((t["status"], "Cancelled" if cancelled else "Confirmed"))
    if d["created_at"]:
        rows.append((t["booked_on"], d["created_at"].strftime("%d %b %Y, %H:%M")))
    return rows


def _html(d, t, cancelled):
    accent = "#b42318" if cancelled else "#176b38"
    soft = "#fdf2f1" if cancelled else "#f3f8f1"
    border = "#f3d0cc" if cancelled else "#dcebd7"
    title = t["x_title"] if cancelled else t["c_title"]
    intro = t["x_intro"] if cancelled else t["c_intro"]
    icon = "✖" if cancelled else "✔"
    detail_rows = "".join(
        f'<tr><td style="padding:10px 0;border-bottom:1px solid #edf1eb;color:#64748b;font-size:13px;width:42%;vertical-align:top;">{_esc(k)}</td>'
        f'<td style="padding:10px 0;border-bottom:1px solid #edf1eb;color:#111827;font-size:14px;font-weight:600;vertical-align:top;">{_esc(v)}</td></tr>'
        for k, v in _rows(d, t, cancelled))
    nxt = ""
    if not cancelled:
        nxt = (f'<div style="margin-top:24px;"><div style="font-size:15px;font-weight:700;color:{accent};margin-bottom:8px;">{_esc(t["next"])}</div>'
               + "".join(f'<div style="font-size:14px;line-height:1.65;color:#374151;padding:3px 0 3px 18px;position:relative;">• {_esc(t[k])}</div>'
                         for k in ("n1", "n2", "n3"))
               + f'<div style="font-size:12.5px;color:#6b7280;margin-top:10px;">{_esc(t["estimate_note"])} {_esc(t["cal"])}</div></div>')
    url = os.getenv("APP_PUBLIC_URL", "").strip()
    button = ""
    if url.startswith(("http://", "https://")):
        button = (f'<div style="text-align:center;margin-top:26px;"><a href="{_esc(url)}" '
                  f'style="display:inline-block;background:{accent};color:#ffffff;text-decoration:none;font-weight:700;'
                  f'font-size:15px;padding:13px 28px;border-radius:10px;">{_esc(t["view"])}</a></div>')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f3f7f2;font-family:Arial,Helvetica,sans-serif;color:#1f2937;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{_esc(title)} · {_esc(d['machine_name'])} · {d['start']:%d %b %Y, %H:%M}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3f7f2;padding:28px 12px;"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:580px;background:#ffffff;border:1px solid #e2eadf;border-radius:18px;overflow:hidden;">
<tr><td style="padding:26px 30px;background:{accent};color:#ffffff;">
<div style="font-size:13px;letter-spacing:1.4px;text-transform:uppercase;opacity:.9;">{_esc(BRAND)}</div>
<div style="font-size:25px;font-weight:700;margin-top:9px;line-height:1.3;">{icon}&nbsp; {_esc(title)}</div>
</td></tr>
<tr><td style="padding:30px;">
<p style="font-size:16px;line-height:1.7;margin:0 0 6px;">{_esc(t["hello"])} <strong>{_esc(d["farmer_name"])}</strong>,</p>
<p style="font-size:15px;line-height:1.7;margin:0 0 20px;color:#374151;">{_esc(intro)}</p>
<div style="background:{soft};border:1px solid {border};border-radius:14px;padding:16px 18px;text-align:center;margin-bottom:18px;">
<div style="font-size:12px;color:#55705a;letter-spacing:1.6px;text-transform:uppercase;">{_esc(d["machine_name"])}</div>
<div style="font-size:22px;font-weight:800;color:{accent};margin-top:6px;">{d["start"]:%d %b %Y}</div>
<div style="font-size:17px;font-weight:700;color:#111827;margin-top:2px;">{d["start"]:%H:%M} – {d["end"]:%H:%M}</div>
</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0">{detail_rows}</table>
{nxt}{button}
</td></tr>
<tr><td style="padding:18px 30px;background:#f8faf8;border-top:1px solid #edf1eb;color:#718071;font-size:12px;line-height:1.6;">{_esc(t["auto"])}</td></tr>
</table><div style="font-size:11px;color:#8a978a;margin-top:16px;">{_esc(t["tagline"])}</div>
</td></tr></table></body></html>'''


def _text(d, t, cancelled):
    title = t["x_title"] if cancelled else t["c_title"]
    intro = t["x_intro"] if cancelled else t["c_intro"]
    lines = [BRAND.upper(), title, "=" * 40, f"{t['hello']} {d['farmer_name']},", intro, ""]
    lines += [f"{k:<20}: {v}" for k, v in _rows(d, t, cancelled)]
    if not cancelled:
        lines += ["", t["next"] + ":"] + [f" - {t[k]}" for k in ("n1", "n2", "n3")] + ["", t["estimate_note"]]
    lines += ["", t["auto"]]
    return "\n".join(lines)


def _send(booking_id, cancelled):
    d = _load(booking_id)
    t = T[d["lang"]]
    host, port, user, password, sender, name = _smtp_settings()

    msg = EmailMessage()
    subject_key = "x_subject" if cancelled else "c_subject"
    msg["Subject"] = f"{t[subject_key]} · #{d['booking_id']} · {d['machine_name']} | {BRAND}"
    msg["From"] = formataddr((name, sender))
    msg["To"] = d["farmer_email"]
    msg.set_content(_text(d, t, cancelled))
    msg.add_alternative(_html(d, t, cancelled), subtype="html")
    msg.add_attachment(_ics(d, cancelled).encode("utf-8"), maintype="text", subtype="calendar",
                       filename=f"booking-{d['booking_id']}.ics")

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=25) as server:
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=25) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.send_message(msg)
    return d["farmer_email"]


def _mask(email):
    try:
        name, domain = email.split("@", 1)
        return f"{name[:2]}{'*' * max(len(name) - 2, 1)}@{domain}"
    except ValueError:
        return email


def _safe(booking_id, cancelled):
    try:
        to = _send(booking_id, cancelled)
        return True, _mask(to)
    except Exception as exc:  # never break the booking flow because of e-mail
        return False, str(exc)[:200]


def send_booking_confirmation(booking_id):
    """Returns (True, masked_email) or (False, reason)."""
    return _safe(booking_id, cancelled=False)


def send_booking_cancellation(booking_id):
    """Returns (True, masked_email) or (False, reason)."""
    return _safe(booking_id, cancelled=True)
