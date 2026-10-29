import os
import re
import math
import html
import calendar
import unicodedata
import io
import csv
from importlib.util import find_spec
from urllib.parse import quote as _urlquote
from pathlib import Path
from datetime import date, time, datetime, timedelta
from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from sqlalchemy import or_, func

from database import (
    init_db, SessionLocal, User, Machine,
    Booking, Bill, Payment
)
from security import (
    validate_registration, hash_password,
    verify_password, send_otp, verify_otp,
    ValidationError, validate_new_password
)
from services import (
    ServiceError, list_approved_machines,
    register_equipment, get_farmer_equipment,
    get_pending_equipment, review_equipment,
    book_machine, get_booked_slots,
    get_farmer_bookings, get_all_bookings,
    update_booking_status, create_bill,
    record_payment, get_billing_report,
    set_machine_service_status,
    # --- new ---
    get_catalogue_machines, check_slot, get_calendar_data, get_service_overview,
    mark_machine_serviced, cancel_booking, get_farmer_bill_map, get_machine_usage,
    get_monthly_report, get_admin_overview, SERVICE_INTERVAL_HOURS,
    # --- new: billing / payments / export ---
    get_invoice, get_farmer_invoices, get_all_invoices, get_billable_bookings,
    create_bill_for_farmer, adjust_bill_hours, get_all_payments
)
from integrations import get_weather, ask_agriculture_ai, IntegrationError
from notifications import send_booking_confirmation, send_booking_cancellation


# =========================================================
# CONFIGURATION
# =========================================================

load_dotenv()

st.set_page_config(
    page_title="Krishi Equipment | Booking & Billing",
    page_icon="🚜",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_NAME = os.getenv(
    "APP_NAME", "Krishi Equipment"
)
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
MANAGER_EMAIL = os.getenv("MANAGER_EMAIL", "").strip().lower()

init_db()

# ---------------------------------------------------------
# UI/UX REVIEW — problems found and fixed in this version
# 1. Secondary buttons turned white-on-white on hover (invisible text).
# 2. Dashboard quick-action buttons set a state key the sidebar never read,
#    so they did nothing. Now wired to the sidebar radio via callbacks.
# 3. Success messages were lost because st.rerun() followed st.success().
#    Added a flash-message helper so feedback survives the rerun.
# 4. Raw Python objects were printed after booking / billing (st.write(result)).
# 5. Status was plain text everywhere. Now colour-coded badges.
# 6. Weather forecast showed numeric condition codes. Now readable text + emoji.
# 7. Login/Register mixed Kannada and English although they must be English.
# 8. Mobile field max_chars=10 blocked the +91 prefix the validator accepts.
# 9. Text colours were not forced, so dark-mode browsers could show low contrast.
# 10. Weak hierarchy: no hero, no cards hover state, default Streamlit chrome.
# 11. No way to resend the OTP.
# 12. "Choose language" / "Admin Dashboard" had no translation entries.
# 13. Registration accepted invalid input (letters in the mobile field, junk
#     names, fake emails). Fields now filter bad characters while typing and
#     are strictly validated on submit.
# ---------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

:root {
  --forest:#0f3d2a; --leaf:#1d8b5a; --leaf-2:#23966b; --lime:#b7ef75;
  --ink:#172b25; --muted:#5c7168; --card:rgba(255,255,255,.92);
  --line:rgba(34,103,68,.14); --radius:20px;
}

/* Apply the font only to text elements. Never to every [class*="st-"] node:
   that overrode the Material icon font and printed "visibility" as text. */
html, body, .stApp,
.stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp input, .stApp textarea, .stApp button,
.stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stMetric"] * {
  font-family:'Plus Jakarta Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
}
/* Safety net: icons always keep their icon font */
.stApp span[data-testid="stIconMaterial"], .stApp .material-icons, .stApp .material-symbols-rounded,
.stApp [class*="material-symbols"], .stApp [data-testid="stIconMaterial"] {
  font-family:'Material Symbols Rounded','Material Icons' !important;
  font-weight:normal !important; letter-spacing:normal !important;
}
#MainMenu, footer { visibility:hidden; }

.stApp {
  background:
    radial-gradient(ellipse at 8% 0%, rgba(183,239,117,.30), transparent 34%),
    radial-gradient(ellipse at 94% 8%, rgba(84,190,164,.22), transparent 32%),
    linear-gradient(145deg,#f4fbf6 0%,#f8fbff 48%,#eef8f2 100%);
  color:var(--ink);
}
.stApp [data-testid="stMarkdownContainer"],
.stApp label, .stApp p, .stApp li { color:var(--ink); }
/* top padding clears Streamlit's fixed header so titles are not cut off */
.block-container { max-width:1440px; padding-top:4.5rem; padding-bottom:3rem; }

/* ---------- Typography ---------- */
.brand { font-size:2.35rem; font-weight:800; color:var(--forest); letter-spacing:-1.2px; line-height:1.15; }
.brand-subtitle { color:var(--muted); font-size:1.02rem; margin-bottom:1.5rem; }
.section-title { color:var(--forest); font-weight:800; }
h1,h2,h3 { letter-spacing:-.45px; color:#143d2d; font-weight:800; }
p, label, [data-testid="stMarkdownContainer"] { line-height:1.6; }

/* ---------- Hero ---------- */
.hero {
  background:linear-gradient(120deg,#0f3d2a 0%,#157a52 55%,#2fae7f 100%);
  color:#fff; border-radius:24px; padding:1.6rem 1.8rem; margin-bottom:1.2rem;
  box-shadow:0 18px 40px rgba(15,61,42,.22); position:relative; overflow:hidden;
}
.hero::after {
  content:""; position:absolute; right:-60px; top:-60px; width:220px; height:220px;
  background:radial-gradient(circle, rgba(183,239,117,.45), transparent 65%);
}
.hero h2, .hero p, .hero div { color:#fff !important; margin:0; }
.hero .hero-title { font-size:1.7rem; font-weight:800; letter-spacing:-.6px; }
.hero .hero-sub { opacity:.9; margin-top:.35rem; font-size:1rem; }

/* ---------- Cards / forms ---------- */
div[data-testid="stForm"], div[data-testid="stVerticalBlockBorderWrapper"] > div {
  border-radius:var(--radius); border-color:var(--line);
}
div[data-testid="stForm"] { background:var(--card); padding:1.5rem; box-shadow:0 12px 36px rgba(19,66,43,.07); }
div[data-testid="stVerticalBlockBorderWrapper"] { transition:transform .18s ease, box-shadow .18s ease; }
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stVerticalBlock"] h3):hover {
  transform:translateY(-2px);
}
div[data-testid="stMetric"] {
  background:linear-gradient(145deg,rgba(255,255,255,.98),rgba(239,250,243,.94));
  border:1px solid rgba(40,119,76,.16); padding:17px; border-radius:18px;
  box-shadow:0 8px 24px rgba(22,75,48,.07);
}
div[data-testid="stMetricLabel"] { color:#4b6a5c; font-weight:650; }
div[data-testid="stMetricValue"] { color:#174a33; font-weight:800; }

/* ---------- Buttons ---------- */
.stButton > button, .stFormSubmitButton > button, div[data-testid="stDownloadButton"] button {
  border-radius:13px; min-height:46px; font-weight:700; border:1px solid rgba(25,111,70,.18);
  background:linear-gradient(115deg,#176b45 0%,#23966b 55%,#49b78a 100%); color:#fff;
  box-shadow:0 6px 15px rgba(28,125,79,.16); transition:transform .15s ease, box-shadow .15s ease;
}
.stButton > button:hover, .stFormSubmitButton > button:hover, div[data-testid="stDownloadButton"] button:hover {
  transform:translateY(-1px); box-shadow:0 10px 22px rgba(28,125,79,.26); color:#fff; border-color:#176b45;
}
.stButton > button:active, .stFormSubmitButton > button:active { transform:translateY(0); }
.stButton > button:focus-visible, .stFormSubmitButton > button:focus-visible {
  outline:3px solid rgba(183,239,117,.9); outline-offset:2px;
}
/* FIX: secondary buttons were white text on white background on hover */
.stButton > button[kind="secondary"], .stFormSubmitButton > button[kind="secondary"] {
  background:rgba(255,255,255,.95); color:#1a6545; box-shadow:none; border:1px solid rgba(25,111,70,.28);
}
.stButton > button[kind="secondary"]:hover, .stFormSubmitButton > button[kind="secondary"]:hover {
  background:#e9f7ee; color:#0f4a31; border-color:#1a6545;
}
/* Button labels live inside a markdown container that the global text colour hit,
   making "Login" dark on green. Force labels to follow the button colour. */
.stApp .stButton button [data-testid="stMarkdownContainer"] *,
.stApp .stFormSubmitButton button [data-testid="stMarkdownContainer"] *,
.stApp [data-testid="stDownloadButton"] button [data-testid="stMarkdownContainer"] * { color:inherit !important; }
.stApp .stButton > button[kind="primary"], .stApp .stFormSubmitButton > button[kind="primary"] { color:#fff !important; }

/* ---------- Sidebar ---------- */
div[data-testid="stSidebar"] { background:linear-gradient(180deg,#e5f5e9 0%,#f4fbf6 55%,#e7f4f1 100%); border-right:1px solid var(--line); }
div[data-testid="stSidebar"] [data-testid="stRadio"] label {
  border-radius:12px; padding:.45rem .7rem; margin-bottom:.15rem; transition:background .15s ease;
}
div[data-testid="stSidebar"] [data-testid="stRadio"] label:hover { background:rgba(29,139,90,.10); }
div[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
  background:rgba(29,139,90,.16); font-weight:700;
}

/* ---------- Inputs ---------- */
/* Style the OUTER wrapper only. Styling the inner <input> as well created the
   double border and the overlapping "Press Enter" hint on password fields. */
div[data-baseweb="input"], div[data-baseweb="textarea"], div[data-baseweb="select"] > div {
  border-radius:12px !important; border:1px solid #cfe3d6 !important;
  background:rgba(255,255,255,.95) !important; overflow:hidden;
}
div[data-baseweb="input"] > div, div[data-baseweb="textarea"] > div { background:transparent !important; border:none !important; }
.stTextInput input, .stTextArea textarea, .stNumberInput input, .stDateInput input, .stTimeInput input {
  background:transparent !important; border:none !important; box-shadow:none !important; color:var(--ink) !important;
}
div[data-baseweb="input"]:focus-within, div[data-baseweb="textarea"]:focus-within, div[data-baseweb="select"]:focus-within > div {
  border-color:var(--leaf) !important; box-shadow:0 0 0 3px rgba(29,139,90,.18) !important;
}
.stTextInput [data-testid="InputInstructions"] { color:var(--muted); }
div[data-testid="stTabs"] button { border-radius:12px 12px 0 0; font-weight:700; }
div[data-testid="stAlert"] { border-radius:14px; }
hr { border-color:rgba(38,115,75,.14); }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:14px; overflow:hidden; }
small, .muted { color:var(--muted); }

/* ---------- Status badges ---------- */
.badge { display:inline-block; padding:.22rem .7rem; border-radius:999px; font-size:.8rem; font-weight:700; letter-spacing:.1px; }
.badge-good { background:#dcf5e5; color:#12673f; }
.badge-warn { background:#fff1cf; color:#8a5a00; }
.badge-bad  { background:#fde1e1; color:#a02323; }
.badge-info { background:#e1ecff; color:#254f9c; }

/* ---------- Auth helper ---------- */
.feature-row { display:flex; align-items:center; gap:.7rem; padding:.6rem .9rem; margin-bottom:.5rem;
  background:var(--card); border:1px solid var(--line); border-radius:14px; }
.feature-row span.ico { font-size:1.3rem; }

@media (max-width: 760px) {
  .block-container { padding-left:1rem; padding-right:1rem; }
  .brand { font-size:1.8rem; }
  .hero { padding:1.2rem; }
  .hero .hero-title { font-size:1.35rem; }
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ---------------------------------------------------------
# NEW: styles for live status cards, timeline bar, calendar and reminders
# ---------------------------------------------------------
CSS_EXTRA = """
<style>
.badge-busy { background:#ffe4cc; color:#9a4a00; }
.chip { display:inline-block; padding:.18rem .6rem; border-radius:10px; font-size:.78rem; font-weight:700; margin:.1rem .25rem .1rem 0; }
.chip-busy { background:#fde1e1; color:#a02323; }
.chip-free { background:#dcf5e5; color:#12673f; }

.mc-head { display:flex; justify-content:space-between; align-items:flex-start; gap:.5rem; }
.mc-name { font-size:1.3rem; font-weight:800; color:var(--forest); letter-spacing:-.4px; }
.mc-code { color:var(--muted); font-size:.8rem; }
.mc-rate { font-size:1.55rem; font-weight:800; color:#174a33; margin:.35rem 0 .2rem; }
.mc-rate small { font-size:.82rem; font-weight:600; color:var(--muted); }

.notice { border-radius:14px; padding:.65rem .95rem; margin:.45rem 0; font-weight:600; font-size:.92rem; line-height:1.45; }
.notice-bad  { background:#fde8e8; color:#8f1d1d; border:1px solid #f4bcbc; }
.notice-warn { background:#fff4d6; color:#7a5200; border:1px solid #f1d58a; }
.notice-good { background:#e2f6e9; color:#12673f; border:1px solid #b7e2c6; }
.notice-info { background:#e6efff; color:#254f9c; border:1px solid #bcd0f5; }

/* booking timeline */
.tl { margin:.4rem 0 .4rem; }
.tl-track { position:relative; height:38px; border-radius:12px; border:1px solid var(--line); overflow:hidden;
  background:repeating-linear-gradient(90deg,#eef8f1 0,#eef8f1 calc(var(--hw) - 1px),#d3e7db calc(var(--hw) - 1px),#d3e7db var(--hw)); }
.tl-seg { position:absolute; top:4px; bottom:4px; border-radius:8px; color:#fff; font-size:.7rem; font-weight:800;
  display:flex; align-items:center; justify-content:center; overflow:hidden; white-space:nowrap; box-sizing:border-box; }
.tl-busy { background:#d9534f; }
.tl-req-ok  { background:rgba(35,150,107,.85); border:2px dashed #0f3d2a; }
.tl-req-bad { background:rgba(217,83,79,.35); border:2px dashed #a02323; color:#7a1d1d; }
.tl-ticks { display:flex; font-size:.7rem; color:var(--muted); margin-top:3px; }
.tl-ticks span { text-align:left; overflow:hidden; }

.legend { display:flex; flex-wrap:wrap; gap:.4rem 1rem; margin:.4rem 0 1rem; font-size:.82rem; color:var(--ink); }
.legend i { display:inline-block; width:14px; height:14px; border-radius:4px; margin-right:.35rem; vertical-align:-2px; }

/* day calendar */
.cal-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:16px; background:var(--card); }
table.cal { border-collapse:collapse; width:100%; min-width:780px; font-size:.78rem; }
table.cal th { background:#e5f5e9; color:var(--forest); padding:.5rem .3rem; font-weight:800; }
table.cal th.now { background:#b7ef75; }
table.cal td { border:1px solid #e1efe6; height:40px; padding:0; text-align:center; }
table.cal td.mname { text-align:left; padding:.3rem .65rem; font-weight:700; white-space:nowrap; background:#f7fcf9; min-width:150px; color:var(--ink); }
table.cal td.mname small { color:var(--muted); font-weight:500; }
table.cal td.free { background:#f2fbf5; }
table.cal td.svc { background:repeating-linear-gradient(45deg,#fbe0e0,#fbe0e0 7px,#f3c3c3 7px,#f3c3c3 14px); color:#8f1d1d; font-weight:800; }

/* month calendar */
.month { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:6px; }
.month .dow { text-align:center; font-weight:800; color:var(--forest); padding:.3rem 0; font-size:.82rem; }
.day { min-height:80px; border-radius:12px; padding:.4rem .5rem; border:1px solid var(--line); font-size:.76rem; background:#fff; color:var(--ink); }
.day b { font-size:.95rem; }
.day span { display:block; color:var(--muted); margin-top:.15rem; }
.day.out { opacity:.35; }
.day.past { opacity:.62; }
.day.today { outline:3px solid #1d8b5a; }
.day.d-free { background:#eaf8ef; }
.day.d-part { background:#fff3d1; }
.day.d-busy { background:#fbdcdc; }
.day.d-svc  { background:#e9e9ee; }
@media (max-width: 760px) {
  .day { min-height:58px; font-size:.64rem; padding:.25rem; }
  .mc-name { font-size:1.1rem; }
}
</style>
"""
st.markdown(CSS_EXTRA, unsafe_allow_html=True)



# =========================================================
# LANGUAGE SUPPORT
# Registration and Login remain English. Other pages use preferred_language.
# =========================================================
LANGUAGES = {"English": "English", "Kannada": "ಕನ್ನಡ", "Hindi": "हिन्दी"}
TRANSLATIONS = {
    "Kannada": {
        "Dashboard": "ಡ್ಯಾಶ್‌ಬೋರ್ಡ್", "Equipment Catalogue": "ಯಂತ್ರಗಳ ಪಟ್ಟಿ",
        "Welcome to your farm equipment booking and billing service.": "ನಿಮ್ಮ ಕೃಷಿ ಯಂತ್ರಗಳ ಬುಕ್ಕಿಂಗ್ ಮತ್ತು ಬಿಲ್ಲಿಂಗ್ ಸೇವೆಗೆ ಸ್ವಾಗತ.",
        "Register Equipment": "ಯಂತ್ರ ನೋಂದಣಿ", "Book Equipment": "ಯಂತ್ರ ಬುಕ್ ಮಾಡಿ",
        "My Bookings": "ನನ್ನ ಬುಕ್ಕಿಂಗ್‌ಗಳು", "Weather & AI": "ಹವಾಮಾನ ಮತ್ತು AI",
        "Admin Menu": "ಆಡ್ಮಿನ್ ಮೆನು", "Manager Menu": "ಮ್ಯಾನೇಜರ್ ಮೆನು",
        "Farmer Menu": "ರೈತರ ಮೆನು", "Equipment Approvals": "ಯಂತ್ರ ಅನುಮೋದನೆಗಳು",
        "Booking Management": "ಬುಕ್ಕಿಂಗ್ ನಿರ್ವಹಣೆ", "Billing": "ಬಿಲ್ಲಿಂಗ್",
        "Payments": "ಪಾವತಿಗಳು", "Equipment Service Status": "ಯಂತ್ರ ಸೇವಾ ಸ್ಥಿತಿ",
        "Monthly Reports": "ಮಾಸಿಕ ವರದಿಗಳು", "Logout": "ಲಾಗ್‌ಔಟ್",
        "Welcome Back": "ಮತ್ತೆ ಸ್ವಾಗತ", "Equipment": "ಯಂತ್ರ",
        "Booking Date": "ಬುಕ್ಕಿಂಗ್ ದಿನಾಂಕ", "Start Time": "ಆರಂಭದ ಸಮಯ",
        "Booking Hours": "ಬುಕ್ಕಿಂಗ್ ಗಂಟೆಗಳು", "Estimated Cost": "ಅಂದಾಜು ವೆಚ್ಚ",
        "Notes (optional)": "ಟಿಪ್ಪಣಿಗಳು (ಐಚ್ಛಿಕ)", "Check Existing Slots": "ಲಭ್ಯ ಸಮಯ ಪರಿಶೀಲಿಸಿ",
        "Confirm Booking": "ಬುಕ್ಕಿಂಗ್ ಖಚಿತಪಡಿಸಿ", "Actual Usage Hours": "ನಿಜವಾದ ಬಳಕೆ ಗಂಟೆಗಳು",
        "Create Bill": "ಬಿಲ್ ರಚಿಸಿ", "Payment Amount (₹)": "ಪಾವತಿ ಮೊತ್ತ (₹)",
        "Payment Method": "ಪಾವತಿ ವಿಧಾನ", "Reference (optional)": "ಉಲ್ಲೇಖ (ಐಚ್ಛಿಕ)",
        "Record Payment": "ಪಾವತಿ ದಾಖಲಿಸಿ", "City / Town": "ನಗರ / ಪಟ್ಟಣ",
        "Get Weather": "ಹವಾಮಾನ ಪಡೆಯಿರಿ", "AI Assistant": "AI ಸಹಾಯಕ",
        "Ask AI": "AI ಅನ್ನು ಕೇಳಿ", "Answer Language": "ಉತ್ತರದ ಭಾಷೆ",
        "Rate": "ದರ", "Status": "ಸ್ಥಿತಿ", "Description": "ವಿವರಣೆ",
        "Approve": "ಅನುಮೋದಿಸಿ", "Reject": "ತಿರಸ್ಕರಿಸಿ",
        "Choose language": "ಭಾಷೆ ಆಯ್ಕೆಮಾಡಿ", "Admin Dashboard": "ಆಡ್ಮಿನ್ ಡ್ಯಾಶ್‌ಬೋರ್ಡ್",
        "Equipment approval management": "ಯಂತ್ರ ಅನುಮೋದನೆ ನಿರ್ವಹಣೆ",
        "Pending approval requests ಇಲ್ಲ.": "ಅನುಮೋದನೆಗಾಗಿ ಕಾಯುತ್ತಿರುವ ವಿನಂತಿಗಳಿಲ್ಲ.",
        "ಈಗ booking ಮಾಡಲು equipment ಲಭ್ಯವಿಲ್ಲ.": "ಈಗ ಬುಕ್ಕಿಂಗ್‌ಗೆ ಯಂತ್ರಗಳು ಲಭ್ಯವಿಲ್ಲ.",
        "ಹೊಂದುವ equipment ಸಿಗಲಿಲ್ಲ.": "ಹೊಂದುವ ಯಂತ್ರ ಸಿಗಲಿಲ್ಲ.",
        "ಲಭ್ಯವಿರುವ equipment ಇಲ್ಲ.": "ಲಭ್ಯವಿರುವ ಯಂತ್ರಗಳಿಲ್ಲ.",
        "ಇನ್ನೂ bookings ಇಲ್ಲ.": "ಇನ್ನೂ ಬುಕ್ಕಿಂಗ್‌ಗಳಿಲ್ಲ.",
        "Bill created.": "ಬಿಲ್ ರಚಿಸಲಾಗಿದೆ.", "Status updated.": "ಸ್ಥಿತಿ ನವೀಕರಿಸಲಾಗಿದೆ.",
        "Equipment status updated.": "ಯಂತ್ರದ ಸ್ಥಿತಿ ನವೀಕರಿಸಲಾಗಿದೆ.",
        "Outstanding payments ಇಲ್ಲ.": "ಬಾಕಿ ಪಾವತಿಗಳಿಲ್ಲ.", "Billing records ಇಲ್ಲ.": "ಬಿಲ್ಲಿಂಗ್ ದಾಖಲೆಗಳಿಲ್ಲ.",
        "Bills ಇಲ್ಲ.": "ಬಿಲ್‌ಗಳಿಲ್ಲ.", "Download CSV": "CSV ಡೌನ್‌ಲೋಡ್ ಮಾಡಿ",
        "Monthly Summary": "ಮಾಸಿಕ ಸಾರಾಂಶ", "Total Billed": "ಒಟ್ಟು ಬಿಲ್ ಮೊತ್ತ",
        "Total Collected": "ಒಟ್ಟು ಸಂಗ್ರಹಿಸಿದ ಮೊತ್ತ", "Outstanding Due": "ಬಾಕಿ ಮೊತ್ತ",
        "Total Bookings": "ಒಟ್ಟು ಬುಕ್ಕಿಂಗ್‌ಗಳು", "Quick actions": "ತ್ವರಿತ ಕ್ರಿಯೆಗಳು",
    },
    "Hindi": {
        "Dashboard": "डैशबोर्ड", "Equipment Catalogue": "उपकरण सूची",
        "Welcome to your farm equipment booking and billing service.": "आपकी कृषि उपकरण बुकिंग और बिलिंग सेवा में आपका स्वागत है।",
        "Register Equipment": "उपकरण पंजीकरण", "Book Equipment": "उपकरण बुक करें",
        "My Bookings": "मेरी बुकिंग", "Weather & AI": "मौसम और AI",
        "Admin Menu": "एडमिन मेनू", "Manager Menu": "मैनेजर मेनू",
        "Farmer Menu": "किसान मेनू", "Equipment Approvals": "उपकरण अनुमोदन",
        "Booking Management": "बुकिंग प्रबंधन", "Billing": "बिलिंग",
        "Payments": "भुगतान", "Equipment Service Status": "उपकरण सेवा स्थिति",
        "Monthly Reports": "मासिक रिपोर्ट", "Logout": "लॉग आउट",
        "Welcome Back": "वापस स्वागत है", "Equipment": "उपकरण",
        "Booking Date": "बुकिंग की तारीख", "Start Time": "शुरू होने का समय",
        "Booking Hours": "बुकिंग के घंटे", "Estimated Cost": "अनुमानित लागत",
        "Notes (optional)": "नोट्स (वैकल्पिक)", "Check Existing Slots": "उपलब्ध समय जांचें",
        "Confirm Booking": "बुकिंग की पुष्टि करें", "Actual Usage Hours": "वास्तविक उपयोग घंटे",
        "Create Bill": "बिल बनाएं", "Payment Amount (₹)": "भुगतान राशि (₹)",
        "Payment Method": "भुगतान का तरीका", "Reference (optional)": "संदर्भ (वैकल्पिक)",
        "Record Payment": "भुगतान दर्ज करें", "City / Town": "शहर / कस्बा",
        "Get Weather": "मौसम देखें", "AI Assistant": "AI सहायक",
        "Ask AI": "AI से पूछें", "Answer Language": "उत्तर की भाषा",
        "Rate": "दर", "Status": "स्थिति", "Description": "विवरण",
        "Approve": "स्वीकृत करें", "Reject": "अस्वीकार करें",
        "Choose language": "भाषा चुनें", "Admin Dashboard": "एडमिन डैशबोर्ड",
        "Equipment approval management": "उपकरण अनुमोदन प्रबंधन",
        "Pending approval requests ಇಲ್ಲ.": "अनुमोदन के लिए कोई अनुरोध लंबित नहीं है।",
        "ಈಗ booking ಮಾಡಲು equipment ಲಭ್ಯವಿಲ್ಲ.": "अभी बुकिंग के लिए उपकरण उपलब्ध नहीं हैं।",
        "ಹೊಂದುವ equipment ಸಿಗಲಿಲ್ಲ.": "कोई मेल खाता उपकरण नहीं मिला।",
        "ಲಭ್ಯವಿರುವ equipment ಇಲ್ಲ.": "कोई उपकरण उपलब्ध नहीं है।",
        "ಇನ್ನೂ bookings ಇಲ್ಲ.": "अभी कोई बुकिंग नहीं है।",
        "Bill created.": "बिल बना दिया गया।", "Status updated.": "स्थिति अपडेट की गई।",
        "Equipment status updated.": "उपकरण की स्थिति अपडेट की गई।",
        "Outstanding payments ಇಲ್ಲ.": "कोई बकाया भुगतान नहीं है।", "Billing records ಇಲ್ಲ.": "बिलिंग रिकॉर्ड उपलब्ध नहीं हैं।",
        "Bills ಇಲ್ಲ.": "कोई बिल नहीं है।", "Download CSV": "CSV डाउनलोड करें",
        "Monthly Summary": "मासिक सारांश", "Total Billed": "कुल बिल राशि",
        "Total Collected": "कुल प्राप्त राशि", "Outstanding Due": "बकाया राशि",
        "Total Bookings": "कुल बुकिंग", "Quick actions": "त्वरित कार्य",
    },
}

def tr(text):
    language = st.session_state.get("app_language", "English")
    if language == "English":
        return text
    return TRANSLATIONS.get(language, {}).get(text, text)

# ---------------------------------------------------------
# NEW: extra translations (status words, new menu items)
# ---------------------------------------------------------
TRANSLATIONS["Kannada"].update({
    "Overview": "ಅವಲೋಕನ", "Calendar": "ಕ್ಯಾಲೆಂಡರ್", "Available": "ಲಭ್ಯ",
    "Booked Now": "ಈಗ ಬುಕ್ ಆಗಿದೆ", "Under Service": "ಸೇವೆಯಲ್ಲಿದೆ", "Unavailable": "ಲಭ್ಯವಿಲ್ಲ",
    "Confirmed": "ದೃಢೀಕೃತ", "Approved": "ಅನುಮೋದಿತ", "In Progress": "ಪ್ರಗತಿಯಲ್ಲಿದೆ",
    "Completed": "ಪೂರ್ಣಗೊಂಡಿದೆ", "Cancelled": "ರದ್ದಾಗಿದೆ", "Pending": "ಬಾಕಿ", "Rejected": "ತಿರಸ್ಕೃತ",
    "Paid": "ಪಾವತಿಸಲಾಗಿದೆ", "Partial": "ಭಾಗಶಃ", "Unpaid": "ಪಾವತಿಯಾಗಿಲ್ಲ",
    "Admin": "ಆಡ್ಮಿನ್", "Manager": "ಮ್ಯಾನೇಜರ್", "Farmer": "ರೈತ",
    "Bill amount (actual hours × rate)": "ಬಿಲ್ ಮೊತ್ತ (ನಿಜವಾದ ಗಂಟೆ × ದರ)",
})
TRANSLATIONS["Hindi"].update({
    "Overview": "अवलोकन", "Calendar": "कैलेंडर", "Available": "उपलब्ध",
    "Booked Now": "अभी बुक है", "Under Service": "सर्विस में", "Unavailable": "उपलब्ध नहीं",
    "Confirmed": "पुष्ट", "Approved": "स्वीकृत", "In Progress": "जारी है",
    "Completed": "पूर्ण", "Cancelled": "रद्द", "Pending": "लंबित", "Rejected": "अस्वीकृत",
    "Paid": "भुगतान हो गया", "Partial": "आंशिक", "Unpaid": "बकाया",
    "Admin": "एडमिन", "Manager": "मैनेजर", "Farmer": "किसान",
    "Bill amount (actual hours × rate)": "बिल राशि (वास्तविक घंटे × दर)",
})


def L(en, kn=None, hi=None):
    """Pick the text for the signed-in user's language (falls back to English)."""
    language = st.session_state.get("app_language", "English")
    if language == "Kannada" and kn:
        return kn
    if language == "Hindi" and hi:
        return hi
    return en


def esc(value):
    return html.escape(str(value if value is not None else ""))


def live(seconds):
    """Auto-refresh a section every N seconds so every logged-in user sees real-time changes.
    Uses st.fragment (Streamlit >= 1.37); on older versions the section simply renders normally."""
    def decorator(fn):
        if hasattr(st, "fragment"):
            try:
                return st.fragment(run_every=seconds)(fn)
            except TypeError:
                return fn
        return fn
    return decorator


# ---------------------------------------------------------
# NEW: business-rule messages in all three languages.
# The service layer raises Kannada/English text; localize_error() shows it in the user's language.
# ---------------------------------------------------------
SLOT_MESSAGES = {
    "ok": {
        "English": "This slot is free — you can confirm the booking.",
        "Kannada": "ಈ ಸಮಯ ಖಾಲಿ ಇದೆ — ಬುಕ್ಕಿಂಗ್ ಖಚಿತಪಡಿಸಬಹುದು.",
        "Hindi": "यह समय खाली है — आप बुकिंग की पुष्टि कर सकते हैं।"},
    "conflict": {
        "English": "This equipment is already booked: Booking #{id}, {start}–{end}. Please choose another time.",
        "Kannada": "ಈ ಯಂತ್ರ ಈಗಾಗಲೇ ಬುಕ್ ಆಗಿದೆ: ಬುಕ್ಕಿಂಗ್ #{id}, {start}–{end}. ಬೇರೆ ಸಮಯ ಆಯ್ಕೆಮಾಡಿ.",
        "Hindi": "यह उपकरण पहले से बुक है: बुकिंग #{id}, {start}–{end}। कृपया दूसरा समय चुनें।"},
    "unavailable": {
        "English": "This equipment is Under Service / Unavailable, so it cannot be booked.",
        "Kannada": "ಈ ಯಂತ್ರ ಸೇವೆಯಲ್ಲಿದೆ / ಲಭ್ಯವಿಲ್ಲ; ಬುಕ್ಕಿಂಗ್ ಸಾಧ್ಯವಿಲ್ಲ.",
        "Hindi": "यह उपकरण सर्विस में है / उपलब्ध नहीं है, इसलिए बुक नहीं किया जा सकता।"},
    "past_date": {
        "English": "Bookings cannot be made for a past date.",
        "Kannada": "ಹಿಂದಿನ ದಿನಾಂಕಕ್ಕೆ ಬುಕ್ಕಿಂಗ್ ಮಾಡಲು ಸಾಧ್ಯವಿಲ್ಲ.",
        "Hindi": "पिछली तारीख के लिए बुकिंग नहीं की जा सकती।"},
    "bad_hours": {
        "English": "A booking must be between 1 and 10 hours.",
        "Kannada": "ಬುಕ್ಕಿಂಗ್ 1ರಿಂದ 10 ಗಂಟೆಗಳವರೆಗೆ ಇರಬೇಕು.",
        "Hindi": "बुकिंग 1 से 10 घंटे की होनी चाहिए।"},
    "midnight": {
        "English": "A booking must finish within the same day; bookings that cross midnight are not supported.",
        "Kannada": "ಬುಕ್ಕಿಂಗ್ ಒಂದೇ ದಿನದೊಳಗೆ ಮುಗಿಯಬೇಕು; ಮಧ್ಯರಾತ್ರಿ ದಾಟುವ ಬುಕ್ಕಿಂಗ್ ಬೆಂಬಲಿತವಲ್ಲ.",
        "Hindi": "बुकिंग उसी दिन समाप्त होनी चाहिए; आधी रात पार करने वाली बुकिंग समर्थित नहीं है।"},
    "not_approved": {
        "English": "This equipment has not been approved by the admin yet.",
        "Kannada": "ಈ ಯಂತ್ರಕ್ಕೆ ಇನ್ನೂ ಆಡ್ಮಿನ್ ಅನುಮೋದನೆ ಸಿಕ್ಕಿಲ್ಲ.",
        "Hindi": "इस उपकरण को अभी तक एडमिन की मंज़ूरी नहीं मिली है।"},
    "machine_missing": {
        "English": "Equipment not found.", "Kannada": "ಯಂತ್ರ ಕಂಡುಬಂದಿಲ್ಲ.", "Hindi": "उपकरण नहीं मिला।"},
    "user_missing": {
        "English": "User account not found. Please log in again.",
        "Kannada": "ಬಳಕೆದಾರ ಖಾತೆ ಕಂಡುಬಂದಿಲ್ಲ. ಮತ್ತೆ ಲಾಗಿನ್ ಮಾಡಿ.",
        "Hindi": "उपयोगकर्ता खाता नहीं मिला। कृपया फिर से लॉगिन करें।"},
    "booking_missing": {
        "English": "Booking not found.", "Kannada": "ಬುಕ್ಕಿಂಗ್ ಕಂಡುಬಂದಿಲ್ಲ.", "Hindi": "बुकिंग नहीं मिली।"},
    "pay_exceed": {
        "English": "A payment cannot be more than the pending amount of ₹{due}.",
        "Kannada": "ಪಾವತಿ ಬಾಕಿ ಮೊತ್ತ ₹{due} ಗಿಂತ ಹೆಚ್ಚಿರಬಾರದು.",
        "Hindi": "भुगतान बकाया राशि ₹{due} से अधिक नहीं हो सकता।"},
    "bill_exists": {
        "English": "A bill has already been created for this booking.",
        "Kannada": "ಈ ಬುಕ್ಕಿಂಗ್‌ಗೆ ಬಿಲ್ ಈಗಾಗಲೇ ಸಿದ್ಧವಾಗಿದೆ.",
        "Hindi": "इस बुकिंग का बिल पहले ही बन चुका है।"},
    "bill_future": {
        "English": "A bill can only be created on or after the day the work was done.",
        "Kannada": "ಕೆಲಸ ನಡೆದ ದಿನಾಂಕದ ನಂತರ ಮಾತ್ರ ಬಿಲ್ ಸಿದ್ಧಪಡಿಸಬಹುದು.",
        "Hindi": "बिल केवल काम होने के दिन या उसके बाद ही बनाया जा सकता है।"},
    "bill_cancelled": {
        "English": "A cancelled booking cannot be billed.",
        "Kannada": "ರದ್ದಾದ ಬುಕ್ಕಿಂಗ್‌ಗೆ ಬಿಲ್ ಮಾಡಲಾಗುವುದಿಲ್ಲ.",
        "Hindi": "रद्द की गई बुकिंग का बिल नहीं बनाया जा सकता।"},
    "bill_hours": {
        "English": "Actual hours must be more than 0 and at most 24.",
        "Kannada": "ನಿಜವಾದ ಗಂಟೆಗಳು 0ಕ್ಕಿಂತ ಹೆಚ್ಚು ಮತ್ತು 24ರೊಳಗೆ ಇರಬೇಕು.",
        "Hindi": "वास्तविक घंटे 0 से अधिक और अधिकतम 24 होने चाहिए।"},
    "completed_locked": {
        "English": "A completed booking cannot be moved back to another status.",
        "Kannada": "ಪೂರ್ಣಗೊಂಡ ಬುಕ್ಕಿಂಗ್ ಸ್ಥಿತಿಯನ್ನು ಹಿಂದಕ್ಕೆ ಬದಲಾಯಿಸಲಾಗುವುದಿಲ್ಲ.",
        "Hindi": "पूर्ण हो चुकी बुकिंग की स्थिति वापस नहीं बदली जा सकती।"},
    "cancel_not_owner": {
        "English": "You can only cancel your own bookings.",
        "Kannada": "ನಿಮ್ಮ ಸ್ವಂತ ಬುಕ್ಕಿಂಗ್ ಮಾತ್ರ ರದ್ದು ಮಾಡಬಹುದು.",
        "Hindi": "आप केवल अपनी बुकिंग रद्द कर सकते हैं।"},
    "cancel_locked": {
        "English": "This booking can no longer be cancelled.",
        "Kannada": "ಈ ಬುಕ್ಕಿಂಗ್ ಅನ್ನು ಇನ್ನು ರದ್ದು ಮಾಡಲಾಗುವುದಿಲ್ಲ.",
        "Hindi": "इस बुकिंग को अब रद्द नहीं किया जा सकता।"},
}

ERROR_PATTERNS = [
    ("ಈಗಾಗಲೇ ಬುಕ್ ಆಗಿದೆ", "conflict"), ("ಹಿಂದಿನ ದಿನಾಂಕಕ್ಕೆ", "past_date"),
    ("1ರಿಂದ 10 ಗಂಟೆ", "bad_hours"), ("ಮಧ್ಯರಾತ್ರಿ", "midnight"),
    ("admin approval ಪಡೆದಿಲ್ಲ", "not_approved"), ("Under Service/Unavailable", "unavailable"),
    ("Payment pending amount", "pay_exceed"), ("ಈ bookingಗೆ bill ಈಗಾಗಲೇ", "bill_exists"),
    ("ಕೆಲಸ ನಡೆದ ದಿನಾಂಕದ ನಂತರ", "bill_future"), ("Cancelled bookingಗೆ bill", "bill_cancelled"),
    ("Actual hours 0ಕ್ಕಿಂತ", "bill_hours"), ("Completed booking ಸ್ಥಿತಿಯನ್ನು", "completed_locked"),
    ("Booking ಕಂಡುಬಂದಿಲ್ಲ", "booking_missing"), ("Machine ಕಂಡುಬಂದಿಲ್ಲ", "machine_missing"),
    ("Equipment ಕಂಡುಬಂದಿಲ್ಲ", "machine_missing"), ("User account ಕಂಡುಬಂದಿಲ್ಲ", "user_missing"),
    ("You can only cancel your own", "cancel_not_owner"), ("can no longer be cancelled", "cancel_locked"),
]


def slot_message(info):
    """Message for a check_slot() result (or an error code) in the user's language."""
    code = info.get("code", "")
    templates = SLOT_MESSAGES.get(code)
    if not templates:
        return str(info.get("message", ""))
    language = st.session_state.get("app_language", "English")
    text = templates.get(language) or templates["English"]
    values = {"id": "", "start": "", "end": "", "due": ""}
    values.update({k: v for k, v in info.items() if k != "code"})
    return text.format(**values)


def localize_error(text):
    """Translate a known backend business-rule error into the user's language."""
    text = str(text)
    for needle, code in ERROR_PATTERNS:
        if needle in text:
            info = {"code": code}
            m = re.search(r"Booking #(\d+), (\d{2}:\d{2})–(\d{2}:\d{2})", text)
            if m:
                info.update(id=m.group(1), start=m.group(2), end=m.group(3))
            m = re.search(r"₹\s*([\d,]+(?:\.\d+)?)", text)
            if m and code == "pay_exceed":
                info["due"] = m.group(1)
            return slot_message(info)
    return text


# ---------------------------------------------------------
# NEW: timeline bar + calendar renderers (HTML, single-line so Markdown never treats it as code)
# ---------------------------------------------------------
def _tfloat(value):
    if isinstance(value, str):
        parts = value.split(":")
        return int(parts[0]) + int(parts[1]) / 60
    return value.hour + value.minute / 60


def timeline_html(slots, request=None):
    """Horizontal day bar. slots: rows from get_booked_slots(); request: (start_h, end_h, is_ok)."""
    segs = [(_tfloat(s["Start"]), _tfloat(s["End"]), f"#{s['Booking ID']}") for s in slots]
    lo, hi = 5, 23
    points = [x for s in segs for x in s[:2]] + (list(request[:2]) if request else [])
    if points:
        lo, hi = min(lo, int(min(points))), max(hi, math.ceil(max(points)))
    span = max(hi - lo, 1)

    def seg(a, b, cls, label, title):
        return (f'<div class="tl-seg {cls}" title="{esc(title)}" style="left:{(a - lo) / span * 100:.3f}%;'
                f'width:{max((b - a) / span * 100, 0.5):.3f}%">{esc(label)}</div>')

    parts = [seg(a, b, "tl-busy", lab, f"{lab}: {int(a):02d}:{int(round((a % 1) * 60)):02d}–{int(b):02d}:{int(round((b % 1) * 60)):02d}")
             for a, b, lab in segs]
    if request:
        a, b, ok = request
        parts.append(seg(a, b, "tl-req-ok" if ok else "tl-req-bad", L("Your slot", "ನಿಮ್ಮ ಸಮಯ", "आपका समय"), "Your slot"))
    step = 1 if span <= 12 else 2
    ticks = "".join(f'<span style="flex:{step}">{h:02d}</span>' for h in range(lo, hi, step))
    return (f'<div class="tl"><div class="tl-track" style="--hw:{100 / span:.4f}%">{"".join(parts)}</div>'
            f'<div class="tl-ticks">{ticks}</div></div>')


def timeline_legend():
    return ('<div class="legend">'
            f'<span><i style="background:#d9534f"></i>{L("Already booked", "ಈಗಾಗಲೇ ಬುಕ್ ಆಗಿದೆ", "पहले से बुक")}</span>'
            f'<span><i style="background:rgba(35,150,107,.85);border:2px dashed #0f3d2a"></i>{L("Your slot (free)", "ನಿಮ್ಮ ಸಮಯ (ಖಾಲಿ)", "आपका समय (खाली)")}</span>'
            f'<span><i style="background:rgba(217,83,79,.35);border:2px dashed #a02323"></i>{L("Your slot (clashes)", "ನಿಮ್ಮ ಸಮಯ (ಸಂಘರ್ಷ)", "आपका समय (टकराव)")}</span>'
            '</div>')


STATUS_COLOURS = {"Confirmed": "#3b82f6", "Approved": "#3b82f6", "In Progress": "#f0932b", "Completed": "#8a9a93"}


def calendar_legend():
    items = [("#eaf8ef", L("Free", "ಖಾಲಿ", "खाली")), ("#3b82f6", L("Confirmed", "ದೃಢೀಕೃತ", "पुष्ट")),
             ("#f0932b", L("In Progress", "ಪ್ರಗತಿಯಲ್ಲಿದೆ", "जारी है")), ("#8a9a93", L("Completed", "ಪೂರ್ಣಗೊಂಡಿದೆ", "पूर्ण")),
             ("repeating-linear-gradient(45deg,#fbe0e0,#fbe0e0 4px,#f1b8b8 4px,#f1b8b8 8px)", L("Under Service", "ಸೇವೆಯಲ್ಲಿದೆ", "सर्विस में"))]
    return '<div class="legend">' + "".join(f'<span><i style="background:{c}"></i>{esc(t)}</span>' for c, t in items) + "</div>"


def _cell_gradient(segments):
    stops, cur = [], 0.0
    for a, b, colour in sorted(segments):
        if a > cur:
            stops.append(f"transparent {cur:.1f}% {a:.1f}%")
        stops.append(f"{colour} {a:.1f}% {b:.1f}%")
        cur = b
    if cur < 100:
        stops.append(f"transparent {cur:.1f}% 100%")
    return f"background:linear-gradient(90deg,{','.join(stops)})"


def calendar_day_html(day, machines, bookings, show_names):
    """Machines x hours grid for one day with coloured booking slots."""
    lo, hi = 6, 21
    for b in bookings:
        lo = min(lo, b["start"].hour)
        hi = max(hi, b["end"].hour + (1 if b["end"].minute else 0))
    hours = list(range(lo, hi))
    now = datetime.now()
    head = "".join(f'<th class="{"now" if day == now.date() and h == now.hour else ""}">{h:02d}</th>' for h in hours)
    rows = []
    for m in machines:
        name = f'<td class="mname">{esc(m["name"])}<br><small>{esc(m["machine_code"])}</small></td>'
        if m["live_status"] in ("Under Service", "Unavailable") and day >= now.date():
            rows.append(f'<tr>{name}<td class="svc" colspan="{len(hours)}">🔧 {esc(tr(m["live_status"]))}</td></tr>')
            continue
        mine = [b for b in bookings if b["machine_id"] == m["id"]]
        cells = []
        for h in hours:
            c_start, c_end = datetime.combine(day, time(h, 0)), datetime.combine(day, time(h, 0)) + timedelta(hours=1)
            segs, tips = [], []
            for b in mine:
                if b["start"] < c_end and c_start < b["end"]:
                    a = (max(b["start"], c_start) - c_start).total_seconds() / 36
                    z = (min(b["end"], c_end) - c_start).total_seconds() / 36
                    segs.append((a, z, STATUS_COLOURS.get(b["status"], "#3b82f6")))
                    who = f" · {b['farmer']}" if show_names and b["farmer"] else ""
                    tips.append(f"#{b['booking_id']} {b['start']:%H:%M}–{b['end']:%H:%M} {b['status']}{who}")
            if segs:
                cells.append(f'<td style="{_cell_gradient(segs)}" title="{esc(" | ".join(tips))}"></td>')
            else:
                cells.append('<td class="free"></td>')
        rows.append(f"<tr>{name}{''.join(cells)}</tr>")
    return (f'<div class="cal-wrap"><table class="cal"><tr><th>{L("Equipment", "ಯಂತ್ರ", "उपकरण")}</th>{head}</tr>'
            f'{"".join(rows)}</table></div>')


def calendar_month_html(year, month, bookings, machine_count, service_block=False):
    today = date.today()
    cal = calendar.Calendar(firstweekday=0)
    names = [L(n, k, h) for n, k, h in [("Mon", "ಸೋಮ", "सोम"), ("Tue", "ಮಂಗಳ", "मंगल"), ("Wed", "ಬುಧ", "बुध"),
                                        ("Thu", "ಗುರು", "गुरु"), ("Fri", "ಶುಕ್ರ", "शुक्र"), ("Sat", "ಶನಿ", "शनि"),
                                        ("Sun", "ಭಾನು", "रवि")]]
    cells = [f'<div class="dow">{n}</div>' for n in names]
    for d in cal.itermonthdates(year, month):
        todays = [b for b in bookings if b["date"] == d]
        hrs = sum(int(b["hours"]) for b in todays)
        ratio = hrs / (10 * max(machine_count, 1))
        if service_block and d >= today:
            tone, text = "d-svc", "🔧"
        elif not todays:
            tone, text = "d-free", L("Free", "ಖಾಲಿ", "खाली")
        else:
            tone = "d-busy" if ratio >= 0.6 else "d-part"
            text = f'{hrs} {L("h", "ಗಂ", "घं")} · {len(todays)} {L("bkg", "ಬುಕ್", "बुक")}'
        cls = f"day {tone}" + (" out" if d.month != month else "") + (" today" if d == today else "") + (" past" if d < today else "")
        cells.append(f'<div class="{cls}"><b>{d.day}</b><span>{esc(text)}</span></div>')
    return f'<div class="month">{"".join(cells)}</div>'


# =========================================================
# SESSION STATE
# =========================================================

if "page" not in st.session_state:
    st.session_state.page = "register"

if "current_user" not in st.session_state:
    st.session_state.current_user = None

if "pending_registration" not in st.session_state:
    st.session_state.pending_registration = None


# =========================================================
# HELPERS
# =========================================================

WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Dense drizzle", 56: "Freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain", 66: "Freezing rain",
    67: "Heavy freezing rain", 71: "Slight snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm",
}


def weather_label(code):
    """Readable condition text with an emoji for a WMO weather code."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "—"
    if code == 0:
        icon = "☀️"
    elif code in (1, 2):
        icon = "🌤️"
    elif code == 3:
        icon = "☁️"
    elif code in (45, 48):
        icon = "🌫️"
    elif code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        icon = "🌧️"
    elif code in (71, 73, 75, 77, 85, 86):
        icon = "❄️"
    elif code in (95, 96, 99):
        icon = "⛈️"
    else:
        icon = "🌡️"
    return f"{icon} {WEATHER_CODES.get(code, 'Conditions')}"


def notify_error(exc):
    st.error(str(exc))


def flash(kind, message):
    """Store a message that survives st.rerun() and is shown on the next run."""
    st.session_state.flash = (kind, message)


def show_flash():
    item = st.session_state.pop("flash", None)
    if not item:
        return
    kind, message = item
    {
        "success": st.success,
        "warning": st.warning,
        "error": st.error,
    }.get(kind, st.info)(message)


def badge(text):
    """Colour-coded status pill (HTML)."""
    label = str(text or "—")
    key = label.strip().lower()
    if key in ("confirmed", "approved", "available", "paid", "completed"):
        cls = "badge-good"
    elif key in ("pending", "in progress", "partial", "under service"):
        cls = "badge-warn"
    elif key in ("booked now",):
        cls = "badge-busy"
    elif key in ("cancelled", "rejected", "unavailable", "overdue", "unpaid"):
        cls = "badge-bad"
    else:
        cls = "badge-info"
    return f'<span class="badge {cls}">{html.escape(tr(label))}</span>'


def call_service(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ServiceError, ValidationError, IntegrationError) as exc:
        st.error(localize_error(str(exc)))
    except Exception as exc:
        st.error(f"ಕಾರ್ಯ ಪೂರ್ಣಗೊಳಿಸಲಾಗಲಿಲ್ಲ: {exc}")
    return None


def role_for_email(email):
    email = (email or "").strip().lower()

    if ADMIN_EMAIL and email == ADMIN_EMAIL:
        return "admin"

    if MANAGER_EMAIL and email == MANAGER_EMAIL:
        return "manager"

    return "farmer"


def money(value):
    try:
        return f"₹{float(value or 0):,.2f}"
    except (ValueError, TypeError):
        return "₹0.00"


def val(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def show_records(records):
    if records is None:
        return

    if not records:
        st.info("ದಾಖಲೆಗಳು ಇನ್ನೂ ಲಭ್ಯವಿಲ್ಲ.")
        return

    output = []
    for record in records:
        if isinstance(record, dict):
            output.append(record)
        elif hasattr(record, "__table__"):
            output.append({
                c.name: getattr(record, c.name, None)
                for c in record.__table__.columns
            })
        else:
            output.append({"Details": str(record)})

    st.dataframe(
        pd.DataFrame(output),
        use_container_width=True,
        hide_index=True,
    )


def logout():
    st.session_state.current_user = None
    st.session_state.page = "login"
    st.session_state.pending_registration = None
    st.rerun()


def machine_text(machine):
    code = val(machine, "machine_code", None) or f"KE-{int(val(machine, 'id', 0)):06d}"
    return (
        f"{code} | {val(machine, 'name', 'Equipment')} | "
        f"{money(val(machine, 'hourly_rate', 0))}/hour"
    )


def booking_text(booking):
    machine = val(booking, "machine")
    name = val(
        booking,
        "machine_name",
        val(machine, "name", "Equipment"),
    )
    return (
        f"#{val(booking, 'id')} | {name} | "
        f"{val(booking, 'booking_date')} | "
        f"{val(booking, 'start_time')} | "
        f"{val(booking, 'status')}"
    )


def go_to(page):
    st.session_state.page = page
    st.rerun()


def set_farmer_nav(page):
    """Callback: runs before the rerun, so it can safely set the sidebar radio value."""
    st.session_state.farmer_nav = page


# =========================================================
# REGISTRATION INPUT VALIDATION
# Every field is checked here, so wrong input can never reach the database.
# =========================================================

RESERVED_USERNAMES = {
    "admin", "administrator", "root", "manager", "support", "system",
    "krishi", "krishiequipment", "test", "user", "username", "null", "none",
}

COMMON_PASSWORDS = {
    "password", "password1", "password@123", "password123", "pass@123",
    "admin123", "admin@123", "welcome123", "welcome@123", "qwerty123",
    "qwerty@123", "abc12345", "abcd1234", "letmein123", "india@123",
    "iloveyou1", "12345678", "123456789", "krishi@123",
}

DISPOSABLE_DOMAINS = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com",
    "temp-mail.org", "yopmail.com", "trashmail.com", "throwawaymail.com",
    "sharklasers.com", "getnada.com", "dispostable.com", "maildrop.cc",
}

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._%+-]{0,62}[A-Za-z0-9])?"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$"
)


def _is_name_char(ch):
    """Letters of any language (including Kannada/Hindi vowel signs), space and . ' -"""
    if ch in " .'-":
        return True
    return unicodedata.category(ch)[0] in ("L", "M")


def clean_name(raw):
    name = re.sub(r"\s+", " ", (raw or "").strip())
    if not name:
        return "", ["Full name is required."]

    errors = []
    if len(name) < 2 or len(name) > 60:
        errors.append("Full name must be 2–60 characters long.")

    if any(not _is_name_char(c) for c in name):
        errors.append(
            "Full name can contain only letters, spaces, dots, apostrophes and hyphens (no digits or symbols)."
        )
    else:
        letters = [c for c in name if unicodedata.category(c)[0] == "L"]
        if len(letters) < 2:
            errors.append("Enter your real full name.")
        elif re.search(r"(.)\1{3,}", name.lower()):
            errors.append("Full name looks invalid. Please enter your real name.")
        elif name[0] in ".'-" or name[-1] in "'-":
            errors.append("Full name cannot start or end with a symbol.")
        elif name.isascii() and not re.search(r"[aeiouyAEIOUY]", name):
            errors.append("Full name looks invalid. Please enter your real name.")

    if not errors and name.isascii() and (name.islower() or name.isupper()):
        name = name.title()
    return name, errors


def clean_phone(raw):
    phone = re.sub(r"[\s\-]", "", raw or "")
    if not phone:
        return "", ["Mobile number is required."]
    if not re.fullmatch(r"[0-9]+", phone):
        return phone, ["Mobile number must contain digits only (0–9)."]
    if not re.fullmatch(r"[6-9][0-9]{9}", phone):
        return phone, ["Enter a valid 10-digit Indian mobile number starting with 6, 7, 8 or 9."]
    if len(set(phone)) <= 2 or phone in ("9876543210", "9123456789"):
        return phone, ["This mobile number looks invalid. Please enter your real number."]
    return phone, []


def clean_email(raw):
    email = (raw or "").strip().lower()
    if not email:
        return "", ["Email is required."]
    if len(email) > 254 or not EMAIL_RE.fullmatch(email) or ".." in email:
        return email, ["Enter a valid email address, for example name@example.com."]
    if email.rsplit("@", 1)[1] in DISPOSABLE_DOMAINS:
        return email, ["Temporary or disposable email addresses are not allowed."]
    return email, []


def clean_username(raw):
    username = (raw or "").strip()
    if not username:
        return "", ["Username is required."]
    if not re.fullmatch(r"[A-Za-z0-9_]{4,30}", username):
        return username, [
            "Username must be 4–30 characters: English letters, numbers and underscore only (no spaces)."
        ]
    if not username[0].isalpha():
        return username, ["Username must start with a letter."]
    if username.lower() in RESERVED_USERNAMES:
        return username, ["This username is reserved. Please choose another one."]
    return username.lower(), []


def check_password(password, confirm, name="", username="", phone="", email=""):
    if not password:
        return ["Password is required."]

    errors = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if len(password) > 64:
        errors.append("Password must be at most 64 characters.")
    if re.search(r"\s", password):
        errors.append("Password cannot contain spaces.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password needs at least one uppercase letter (A–Z).")
    if not re.search(r"[a-z]", password):
        errors.append("Password needs at least one lowercase letter (a–z).")
    if not re.search(r"\d", password):
        errors.append("Password needs at least one number (0–9).")
    if not re.search(r"[^A-Za-z0-9\s]", password):
        errors.append("Password needs at least one special character, for example @ # $ % !")
    if password.lower() in COMMON_PASSWORDS:
        errors.append("This password is too common. Choose a stronger one.")
    if re.search(r"(.)\1{3,}", password):
        errors.append("Password cannot repeat the same character 4 or more times in a row.")

    low = password.lower()
    personal = [username.lower(), (email.split("@")[0] if email else "").lower(), phone]
    personal += [p.lower() for p in name.split() if len(p) >= 4]
    if any(p and len(p) >= 4 and p in low for p in personal):
        errors.append("Password must not contain your name, username, email or mobile number.")

    if password != confirm:
        errors.append("Password and Confirm Password must match.")
    return errors


def validate_registration_form(full_name, phone, email, username, password, confirm):
    """Returns (cleaned_values, error_list). Reports every problem at once."""
    errors = []
    name_c, e = clean_name(full_name)
    errors += e
    phone_c, e = clean_phone(phone)
    errors += e
    email_c, e = clean_email(email)
    errors += e
    user_c, e = clean_username(username)
    errors += e
    errors += check_password(password, confirm, name_c, user_c, phone_c, email_c)
    return {
        "full_name": name_c,
        "phone": phone_c,
        "email": email_c,
        "username": user_c,
    }, errors


def live_input_filters():
    """Blocks wrong characters while the user types (no design change).

    Mobile: digits only, max 10.  Name: letters only.  Username: letters,
    numbers, underscore.  Email / passwords: no spaces.
    """
    components.html(
        r"""
        <script>
        (function () {
          var doc = window.parent.document;
          var rules = {
            "Full Name *":        /[^\p{L}\p{M} .'\-]/gu,
            "Mobile Number *":    /\D/g,
            "Email *":            /\s/g,
            "Username *":         /[^A-Za-z0-9_]/g,
            "Password *":         /\s/g,
            "Confirm Password *": /\s/g
          };
          var maxLen = { "Mobile Number *": 10 };

          function setValue(el, value) {
            var setter = Object.getOwnPropertyDescriptor(
              window.parent.HTMLInputElement.prototype, "value").set;
            setter.call(el, value);
            el.dispatchEvent(new window.parent.Event("input", { bubbles: true }));
          }

          function attach() {
            Object.keys(rules).forEach(function (label) {
              doc.querySelectorAll('input[aria-label="' + label + '"]').forEach(function (el) {
                if (el.dataset.krishiFilter) return;
                el.dataset.krishiFilter = "1";
                el.addEventListener("input", function () {
                  var v = el.value.replace(rules[label], "");
                  if (maxLen[label]) v = v.slice(0, maxLen[label]);
                  if (v !== el.value) setValue(el, v);
                });
              });
            });
          }
          attach();
          setInterval(attach, 500);
        })();
        </script>
        """,
        height=0,
    )


# =========================================================
# HEADER
# =========================================================

def header():
    st.markdown(
        '<div class="brand">🌱 Krishi Equipment</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="brand-subtitle">'
        'Farm equipment booking and billing — all in one place'
        '</div>',
        unsafe_allow_html=True,
    )


def hero(title, subtitle=""):
    st.markdown(
        f'<div class="hero"><div class="hero-title">{title}</div>'
        f'<div class="hero-sub">{subtitle}</div></div>',
        unsafe_allow_html=True,
    )


# =========================================================
# REGISTRATION — FIRST PAGE
# =========================================================

def registration_page():
    header()

    left, right = st.columns([1.05, 1], gap="large")

    with left:
        hero(
            "Simple service for farmers",
            "Find farm equipment, choose an available time, book it, and review your bill.",
        )

        st.markdown("### What can you do with your account?")
        st.markdown(
            """
            <div class="feature-row"><span class="ico">🚜</span><span>Browse available equipment</span></div>
            <div class="feature-row"><span class="ico">📅</span><span>Book equipment by date and time</span></div>
            <div class="feature-row"><span class="ico">🧾</span><span>View bills and payment details</span></div>
            <div class="feature-row"><span class="ico">🌦️</span><span>Check weather information</span></div>
            <div class="feature-row"><span class="ico">🤖</span><span>Get AI help for agriculture questions</span></div>
            """,
            unsafe_allow_html=True,
        )

        st.info(
            "Already have an account? Use the Login button below the form."
        )

    with right:
        st.markdown("## Create an account")
        st.caption("Enter the details below to create your account.")

        with st.form("register_form", clear_on_submit=False):
            full_name = st.text_input(
                "Full Name *",
                placeholder="Enter your full name",
                max_chars=60,
            )
            phone = st.text_input(
                "Mobile Number *",
                placeholder="Enter 10-digit mobile number",
                max_chars=10,
            )
            email = st.text_input(
                "Email *",
                placeholder="you@example.com",
                max_chars=254,
            )
            username = st.text_input(
                "Username *",
                placeholder="e.g. farmer123",
                max_chars=30,
                help="4–30 characters: English letters, numbers and underscore only.",
            )
            password = st.text_input(
                "Password *",
                type="password",
                max_chars=64,
                help="At least 8 characters with an uppercase letter, a lowercase letter, a number and a symbol.",
            )
            confirm = st.text_input(
                "Confirm Password *",
                type="password",
                max_chars=64,
            )
            preferred_language = st.selectbox(
                "Choose your language *",
                ["English", "Kannada", "Hindi"],
                format_func=lambda x: LANGUAGES[x],
            )

            st.caption(
                "All fields marked * are required. "
                "Never share your password with anyone."
            )

            submit = st.form_submit_button(
                "Get Email OTP",
                type="primary",
                use_container_width=True,
            )

        if submit:
            cleaned_values, errors = validate_registration_form(
                full_name, phone, email, username, password, confirm
            )

            name = cleaned_values["full_name"]
            phone_clean = cleaned_values["phone"]
            email_clean = cleaned_values["email"]
            username_clean = cleaned_values["username"]

            if errors:
                st.error("Please fix the following:\n\n" + "\n".join(f"- {e}" for e in errors))
            else:
                try:
                    with SessionLocal() as db:
                        duplicate_errors = []
                        if db.query(User).filter(User.email == email_clean).first():
                            duplicate_errors.append("This email is already registered.")
                        if db.query(User).filter(User.phone == phone_clean).first():
                            duplicate_errors.append("This mobile number is already registered.")
                        if db.query(User).filter(
                            func.lower(User.username) == username_clean
                        ).first():
                            duplicate_errors.append("This username is already taken. Try another one.")

                        if duplicate_errors:
                            st.error(
                                "\n\n".join(duplicate_errors)
                                + "\n\nIf this is your account, please use Login."
                            )
                        else:
                            # Reuse the existing module's validation.
                            data = {
                                "full_name": name,
                                "email": email_clean,
                                "phone": phone_clean,
                                "username": username_clean,
                                "address": "",
                                "village": "",
                                "password": password,
                                "confirm_password": confirm,
                            }

                            try:
                                cleaned = validate_registration(data)
                            except ValidationError as exc:
                                st.error(str(exc))
                                cleaned = None

                            if cleaned:
                                send_otp(email_clean, db)

                                cleaned["full_name"] = name
                                cleaned["email"] = email_clean
                                cleaned["phone"] = phone_clean
                                cleaned["username"] = username_clean
                                cleaned["password"] = password
                                cleaned["preferred_language"] = preferred_language

                                st.session_state.pending_registration = cleaned
                                st.session_state.otp_email = email_clean
                                st.session_state.page = "verify_otp"
                                st.rerun()

                except (ValidationError, IntegrationError) as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"Registration error: {exc}")

        st.divider()
        st.write("Already have an account?")
        if st.button(
            "Login",
            use_container_width=True,
        ):
            go_to("login")

        # Filters wrong characters live while typing in the form above.
        live_input_filters()


# =========================================================
# OTP VERIFICATION
# =========================================================

def otp_page():
    header()
    st.title("📧 Email Verification")
    st.write(
        f"Enter the OTP sent to your email: "
        f"**{st.session_state.get('otp_email', '')}**"
    )
    st.caption("The OTP usually expires in 10 minutes. Check your spam folder if you cannot find it.")

    with st.form("otp_form"):
        otp = st.text_input("6-digit OTP", max_chars=6, placeholder="123456")
        verify = st.form_submit_button(
            "Verify & Create Account",
            type="primary",
            use_container_width=True,
        )

    if verify:
        if not re.fullmatch(r"[0-9]{6}", otp.strip()):
            st.error("Enter a valid 6-digit OTP (digits only).")
            return

        pending = st.session_state.get("pending_registration")
        email = st.session_state.get("otp_email")

        if not pending or not email:
            st.error("Your registration session has expired. Please register again.")
            return

        try:
            with SessionLocal() as db:
                valid = verify_otp(email, otp.strip(), db)

                if not valid:
                    st.error("The OTP is incorrect or has expired.")
                    return

                duplicate = db.query(User).filter(
                    or_(
                        User.email == email,
                        User.phone == pending["phone"],
                        func.lower(User.username) == pending["username"],
                    )
                ).first()

                if duplicate:
                    st.error(
                        "An account with these details already exists. Please log in."
                    )
                    return

                user = User(
                    full_name=pending["full_name"],
                    email=email,
                    phone=pending["phone"],
                    username=pending["username"],
                    address="",
                    village="",
                    password_hash=hash_password(pending["password"]),
                    role=role_for_email(email),
                    preferred_language=pending.get("preferred_language", "English"),
                    active=True,
                )

                db.add(user)
                db.commit()

            st.session_state.pending_registration = None
            st.session_state.pop("otp_email", None)
            flash("success", "Account created successfully. Please log in.")
            st.session_state.page = "login"
            st.rerun()

        except Exception as exc:
            st.error(f"OTP verification error: {exc}")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Resend OTP", use_container_width=True):
            email = st.session_state.get("otp_email")
            if not email:
                st.error("Your registration session has expired. Please register again.")
            else:
                try:
                    with SessionLocal() as db:
                        send_otp(email, db)
                    st.success("A new OTP has been sent to your email.")
                except Exception as exc:
                    st.error(f"Could not resend OTP: {exc}")
    with c2:
        if st.button("Back to Registration", use_container_width=True):
            st.session_state.page = "register"
            st.rerun()


# =========================================================
# LOGIN
# =========================================================

def login_page():
    header()
    show_flash()

    _, centre, _ = st.columns([1, 1.4, 1])
    with centre:
        st.title("👋 Welcome Back")
        st.write("Sign in to your account.")

        with st.form("login_form"):
            identity = st.text_input(
                "Email or Username",
                placeholder="Email / Username",
            )
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button(
                "Login",
                type="primary",
                use_container_width=True,
            )

        if st.button("Forgot Password?", use_container_width=True, key="goto_forgot_password"):
            st.session_state.pop("reset_email", None)
            go_to("forgot_password")

        if submit:
            if not identity.strip() or not password:
                st.error("Both Email/Username and Password are required.")
                return

            try:
                with SessionLocal() as db:
                    user = db.query(User).filter(
                        or_(
                            User.email == identity.strip().lower(),
                            func.lower(User.username) == identity.strip().lower(),
                        )
                    ).first()

                    if not user:
                        st.error("Account not found. Please register first.")
                        return

                    if not user.active:
                        st.error("This account is inactive.")
                        return

                    if not verify_password(password, user.password_hash):
                        st.error("Incorrect password.")
                        return

                    role = role_for_email(user.email)
                    user.role = role
                    db.commit()

                    st.session_state.current_user = {
                        "id": user.id,
                        "full_name": user.full_name,
                        "email": user.email,
                        "username": user.username,
                        "role": role,
                        "preferred_language": user.preferred_language or "English",
                    }
                    st.session_state.app_language = user.preferred_language or "English"

                    st.session_state.page = "dashboard"
                    st.rerun()

            except Exception as exc:
                st.error(f"Login error: {exc}")

        st.divider()
        st.write("New user?")
        if st.button("Create Account", use_container_width=True):
            go_to("register")


# =========================================================
# FORGOT PASSWORD (email OTP)
# =========================================================

def _mask_email(email):
    name, _, domain = str(email).partition("@")
    if len(name) <= 2:
        masked = name[:1] + "*"
    else:
        masked = name[:2] + "*" * (len(name) - 2)
    return f"{masked}@{domain}"


def _leave_forgot_password():
    st.session_state.pop("reset_email", None)
    st.session_state.page = "login"
    st.rerun()


def forgot_password_page():
    header()
    _, centre, _ = st.columns([1, 1.4, 1])
    with centre:
        st.title("🔑 Forgot Password")
        reset_email = st.session_state.get("reset_email")

        # ---------- Step 1: find the account and send the OTP ----------
        if not reset_email:
            st.write("Enter your registered email or username. We will send an OTP to the email saved in your account.")
            with st.form("forgot_request_form"):
                identity = st.text_input("Email or Username", placeholder="Email / Username")
                send = st.form_submit_button("Send OTP", type="primary", use_container_width=True)

            if send:
                ident = identity.strip().lower()
                if not ident:
                    st.error("Enter your Email or Username.")
                else:
                    found_email = None
                    try:
                        with SessionLocal() as db:
                            user = db.query(User).filter(
                                or_(
                                    User.email == ident,
                                    func.lower(User.username) == ident,
                                )
                            ).first()
                            if not user:
                                st.error("Account not found. Please check the details or register first.")
                            elif not user.active:
                                st.error("This account is inactive.")
                            else:
                                send_otp(user.email, db, purpose="reset")
                                found_email = user.email
                    except ValidationError as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f"Could not send OTP: {exc}")
                    if found_email:
                        st.session_state.reset_email = found_email
                        flash("success", "OTP sent to your registered email.")
                        st.rerun()

        # ---------- Step 2: OTP + new password ----------
        else:
            show_flash()
            st.write(f"Enter the OTP sent to **{_mask_email(reset_email)}** and choose a new password.")
            st.caption("The OTP expires in 10 minutes. Check your spam folder if you cannot find it.")
            with st.form("forgot_reset_form"):
                otp = st.text_input("6-digit OTP", max_chars=6, placeholder="123456")
                new_password = st.text_input("New Password", type="password")
                confirm_password = st.text_input("Re-enter New Password", type="password")
                reset = st.form_submit_button("Reset Password", type="primary", use_container_width=True)
            st.caption("Password: 8–72 characters with uppercase, lowercase, a number and a special character.")

            if reset:
                try:
                    if not re.fullmatch(r"[0-9]{6}", otp.strip()):
                        raise ValidationError("Enter a valid 6-digit OTP (digits only).")
                    # Check the new password first so a typo does not use up the OTP.
                    validate_new_password(new_password, confirm_password)
                    updated = False
                    with SessionLocal() as db:
                        verify_otp(reset_email, otp.strip(), db)
                        user = db.query(User).filter(User.email == reset_email).first()
                        if not user:
                            st.error("Account not found. Please register first.")
                        else:
                            user.password_hash = hash_password(new_password)
                            db.commit()
                            updated = True
                    if updated:
                        st.session_state.pop("reset_email", None)
                        flash("success", "Password changed successfully. Please log in with your new password.")
                        st.session_state.page = "login"
                        st.rerun()
                except ValidationError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f"Password reset error: {exc}")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Resend OTP", use_container_width=True, key="forgot_resend"):
                    try:
                        with SessionLocal() as db:
                            send_otp(reset_email, db, purpose="reset")
                        st.success("A new OTP has been sent to your email.")
                    except Exception as exc:
                        st.error(f"Could not resend OTP: {exc}")
            with c2:
                if st.button("Use another account", use_container_width=True, key="forgot_other"):
                    st.session_state.pop("reset_email", None)
                    st.rerun()

        st.divider()
        if st.button("Back to Login", use_container_width=True, key="forgot_back"):
            _leave_forgot_password()


# =========================================================
# ADMIN PANEL
# =========================================================

def admin_panel():
    # Refresh only this view through Streamlit's normal rerun; login/session stays intact.
    title_col, refresh_col = st.columns([5, 1])
    with title_col:
        st.title("🛡️ " + tr("Admin Dashboard"))
    with refresh_col:
        st.write("")
        if st.button("🔄 Refresh", key="refresh_admin_approvals", use_container_width=True):
            st.rerun()
    st.caption(tr("Equipment approval management"))

    pending = call_service(get_pending_equipment)
    if pending is None:
        return

    if not pending:
        st.success(tr("Pending approval requests ಇಲ್ಲ."))
        return

    st.metric("Pending requests", len(pending))

    for machine in pending:
        mid = val(machine, "id")
        with st.container(border=True):
            machine_code = val(machine, "machine_code", None) or f"KE-{int(mid):06d}"
            st.subheader(f"{val(machine, 'name', 'Equipment')} — {machine_code}")
            d1, d2 = st.columns(2)
            with d1:
                st.write(f"💰 **Rate:** {money(val(machine, 'hourly_rate', 0))}/hour")
            with d2:
                st.write(f"📞 **Contact:** {val(machine, 'contact_phone', '') or '-'}")
                st.write(f"📝 **Description:** {val(machine, 'description', '') or '-'}")

            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ " + tr("Approve"), key=f"approve_{mid}",
                             type="primary", use_container_width=True):
                    result = call_service(review_equipment, mid, "Approved")
                    if result is not None:
                        flash("success", "Equipment approved.")
                        st.rerun()

            with c2:
                if st.button("✖ " + tr("Reject"), key=f"reject_{mid}",
                             use_container_width=True):
                    result = call_service(review_equipment, mid, "Rejected")
                    if result is not None:
                        flash("warning", "Equipment rejected.")
                        st.rerun()


# =========================================================
# FARMER DASHBOARD
# =========================================================

def farmer_catalogue():
    st.title("🚜 " + tr("Equipment Catalogue"))
    st.caption(L("Live availability — this page refreshes automatically, so every user sees the same real-time status.",
                 "ನೇರ ಲಭ್ಯತೆ — ಈ ಪುಟ ತಾನಾಗಿ ನವೀಕರಣವಾಗುತ್ತದೆ; ಎಲ್ಲಾ ಬಳಕೆದಾರರಿಗೂ ಒಂದೇ ನೈಜ-ಸಮಯದ ಸ್ಥಿತಿ ಕಾಣುತ್ತದೆ.",
                 "लाइव उपलब्धता — यह पेज अपने आप रिफ्रेश होता है, इसलिए सभी उपयोगकर्ताओं को एक जैसी स्थिति दिखती है।"))
    _catalogue_live()


@live(10)
def _catalogue_live():
    machines = call_service(get_catalogue_machines)
    if not machines:
        st.info(tr("ಈಗ booking ಮಾಡಲು equipment ಲಭ್ಯವಿಲ್ಲ."))
        return

    counts = {k: sum(1 for m in machines if m["live_status"] == k)
              for k in ("Available", "Booked Now", "Under Service", "Unavailable")}
    k1, k2, k3 = st.columns(3)
    k1.metric("🟢 " + tr("Available"), counts["Available"])
    k2.metric("🟠 " + tr("Booked Now"), counts["Booked Now"])
    k3.metric("🔴 " + tr("Under Service"), counts["Under Service"] + counts["Unavailable"])

    f1, f2 = st.columns([3, 2])
    with f1:
        query = st.text_input("🔍 " + L("Search equipment", "ಯಂತ್ರ ಹುಡುಕಿ", "उपकरण खोजें"),
                              placeholder="Tractor, Harvester...", key="cat_query")
    with f2:
        wanted = st.selectbox(
            tr("Status"), ["All", "Available", "Booked Now", "Under Service", "Unavailable"],
            format_func=lambda x: L("All", "ಎಲ್ಲವೂ", "सभी") if x == "All" else tr(x), key="cat_filter")

    filtered = [m for m in machines
                if query.lower() in str(m["name"]).lower() and (wanted == "All" or m["live_status"] == wanted)]
    if not filtered:
        st.info(tr("ಹೊಂದುವ equipment ಸಿಗಲಿಲ್ಲ."))
        return
    st.caption(f"{len(filtered)} / {len(machines)}")

    cols = st.columns(3)
    for index, m in enumerate(filtered):
        live_status = m["live_status"]
        with cols[index % 3]:
            with st.container(border=True):
                st.markdown(
                    f'<div class="mc-head"><div><div class="mc-name">{esc(m["name"])}</div>'
                    f'<div class="mc-code">{L("Equipment ID", "ಯಂತ್ರ ID", "उपकरण ID")}: {esc(m["machine_code"])}</div></div>'
                    f'<div>{badge(live_status)}</div></div>'
                    f'<div class="mc-rate">{money(m["hourly_rate"])} <small>/ {L("hour", "ಗಂಟೆ", "घंटा")}</small></div>',
                    unsafe_allow_html=True)
                st.write(m["description"] or L("Farm equipment", "ಕೃಷಿ ಯಂತ್ರ", "कृषि उपकरण"))

                if live_status in ("Under Service", "Unavailable"):
                    st.markdown(f'<div class="notice notice-bad">🔧 {L("Under service — cannot be booked right now.", "ಸೇವೆಯಲ್ಲಿದೆ — ಈಗ ಬುಕ್ ಮಾಡಲು ಸಾಧ್ಯವಿಲ್ಲ.", "सर्विस में है — अभी बुक नहीं किया जा सकता।")}</div>',
                                unsafe_allow_html=True)
                elif live_status == "Booked Now":
                    until = m["busy_until"].strftime("%H:%M") if m["busy_until"] else ""
                    st.markdown(f'<div class="notice notice-warn">⏳ {L(f"In use until {until}. You can still book a later slot.", f"{until} ವರೆಗೆ ಬಳಕೆಯಲ್ಲಿದೆ. ನಂತರದ ಸಮಯವನ್ನು ಬುಕ್ ಮಾಡಬಹುದು.", f"{until} तक उपयोग में है। आप बाद का समय बुक कर सकते हैं।")}</div>',
                                unsafe_allow_html=True)
                else:
                    nxt = m["next_slot"]
                    extra = f' · {L("Next booking", "ಮುಂದಿನ ಬುಕ್ಕಿಂಗ್", "अगली बुकिंग")}: {esc(nxt)}' if nxt else ""
                    st.markdown(f'<div class="notice notice-good">✅ {L("Free right now", "ಈಗ ಖಾಲಿ ಇದೆ", "अभी खाली है")}{extra}</div>',
                                unsafe_allow_html=True)

                if m["today_slots"]:
                    chips = "".join(f'<span class="chip chip-busy">{esc(s)}</span>' for s in m["today_slots"])
                    st.markdown(f'<div><small>{L("Booked today", "ಇಂದು ಬುಕ್ ಆಗಿರುವುದು", "आज बुक")}:</small><br>{chips}</div>',
                                unsafe_allow_html=True)
                else:
                    st.markdown(f'<span class="chip chip-free">{L("No bookings today", "ಇಂದು ಬುಕ್ಕಿಂಗ್ ಇಲ್ಲ", "आज कोई बुकिंग नहीं")}</span>',
                                unsafe_allow_html=True)

                can_book = live_status in ("Available", "Booked Now")
                if st.button("📅 " + tr("Book Equipment"), key=f"cat_book_{m['id']}", use_container_width=True,
                             disabled=not can_book, type="primary" if can_book else "secondary"):
                    st.session_state.book_machine_id = m["id"]
                    st.session_state._nav_request = "Book Equipment"
                    st.rerun()




def farmer_register_machine():
    user = st.session_state.current_user
    # Refresh this view without logging the farmer out.
    title_col, refresh_col = st.columns([5, 1])
    with title_col:
        st.title("➕ " + tr("Register Equipment"))
    with refresh_col:
        st.write("")
        if st.button("🔄 Refresh", key="refresh_farmer_equipment", use_container_width=True):
            st.rerun()
    st.info(L("Your equipment becomes available for booking only after the admin approves it.",
              "ಆಡ್ಮಿನ್ ಅನುಮೋದಿಸಿದ ನಂತರವೇ ನಿಮ್ಮ ಯಂತ್ರ ಬುಕ್ಕಿಂಗ್‌ಗೆ ಲಭ್ಯವಾಗುತ್ತದೆ.",
              "एडमिन की मंज़ूरी के बाद ही आपका उपकरण बुकिंग के लिए उपलब्ध होगा।"))

    with st.form("equipment_form"):
        kind = st.selectbox(
            "Equipment Type",
            ["Tractor", "Rotavator", "Power tiller", "Sprayer", "Harvester", "Other"],
        )
        custom = st.text_input("Other Equipment Name") if kind == "Other" else ""
        rate = st.number_input("Hourly Rate (₹)", min_value=1.0, max_value=100000.0, value=600.0)
        description = st.text_area("Description (optional)")
        phone = st.text_input("Contact Mobile *", max_chars=10, placeholder="10-digit mobile number")
        submit = st.form_submit_button("Submit for Approval", type="primary", use_container_width=True)

    if submit:
        name = custom.strip() if kind == "Other" else kind

        if not name:
            st.error("Equipment name ಕಡ್ಡಾಯ.")
            return
        if not re.fullmatch(r"[6-9]\d{9}", phone.strip()):
            st.error("ಸರಿಯಾದ 10-digit mobile number ನಮೂದಿಸಿ.")
            return

        result = call_service(
            register_equipment,
            user["id"], name, rate, description.strip(),
            "", phone.strip(),          # location is no longer collected
        )
        if result is not None:
            flash("success", L("Equipment sent for approval.", "ಯಂತ್ರವನ್ನು ಅನುಮೋದನೆಗೆ ಕಳುಹಿಸಲಾಗಿದೆ.",
                               "उपकरण अनुमोदन के लिए भेजा गया।"))
            st.rerun()

    st.divider()
    st.subheader(L("My Equipment", "ನನ್ನ ಯಂತ್ರಗಳು", "मेरे उपकरण"))
    records = call_service(get_farmer_equipment, user["id"])
    if records:
        show_records([{
            "ID": val(r, "machine_code", None) or f"KE-{int(val(r, 'id', 0)):06d}",
            "Equipment": val(r, "name", ""), "Rate (₹/h)": val(r, "hourly_rate", 0),
            "Approval": val(r, "approval_status", ""), "Status": val(r, "status", ""),
            "Contact": val(r, "contact_phone", ""), "Description": val(r, "description", ""),
        } for r in records])
    else:
        show_records(records)


def farmer_booking():
    user = st.session_state.current_user
    st.title("📅 " + tr("Book Equipment"))

    machines = call_service(get_catalogue_machines)
    if not machines:
        st.info(tr("ಲಭ್ಯವಿರುವ equipment ಇಲ್ಲ."))
        return

    by_id = {m["id"]: m for m in machines}
    ids = list(by_id.keys())
    if st.session_state.get("book_machine_id") not in by_id:
        st.session_state.pop("book_machine_id", None)

    with st.container(border=True):
        machine_id = st.selectbox(
            tr("Equipment"), ids,
            format_func=lambda x: f"{machine_text(by_id[x])}  ·  {tr(by_id[x]['live_status'])}",
            key="book_machine_id",
        )

        c1, c2 = st.columns(2)
        with c1:
            booking_date = st.date_input(tr("Booking Date"), min_value=date.today(), value=date.today())
        with c2:
            start = st.time_input(tr("Start Time"), value=time(9, 0))

        hours = st.selectbox(
            tr("Booking Hours"), list(range(1, 11)),
            format_func=lambda h: f"{h} hour" if h == 1 else f"{h} hours",
        )
        rate = float(val(by_id[machine_id], "hourly_rate", 0))
        st.metric(tr("Estimated Cost"), money(rate * hours))
        st.caption(L("Final bill = hours actually used × hourly rate (set by the admin after the work).",
                     "ಅಂತಿಮ ಬಿಲ್ = ನಿಜವಾಗಿ ಬಳಸಿದ ಗಂಟೆ × ಗಂಟೆಯ ದರ (ಕೆಲಸದ ನಂತರ ಆಡ್ಮಿನ್ ನಮೂದಿಸುತ್ತಾರೆ).",
                     "अंतिम बिल = वास्तव में उपयोग किए गए घंटे × प्रति घंटा दर (काम के बाद एडमिन दर्ज करेगा)।"))
        notes = st.text_area(tr("Notes (optional)"))

        # Live pre-check: the same rules the backend enforces, shown BEFORE the click.
        slot = call_service(check_slot, machine_id, booking_date, start, hours) or {"ok": False, "code": "error", "message": ""}
        if slot["ok"]:
            st.success(slot_message(slot))
        elif slot.get("code") != "error":
            st.error(slot_message(slot))
        confirm = st.button("✅ " + tr("Confirm Booking"), type="primary", use_container_width=True,
                            disabled=not slot["ok"])

    _slot_panel(machine_id, booking_date, start, hours)

    if confirm:
        try:
            result = book_machine(user["id"], machine_id, booking_date, start, hours, notes.strip())
        except (ServiceError, ValidationError, IntegrationError) as exc:
            # Another user may have just taken the slot: show the localised reason and refresh the timeline.
            flash("error", localize_error(str(exc)))
            st.rerun()
        except Exception as exc:
            flash("error", f"ಕಾರ್ಯ ಪೂರ್ಣಗೊಳಿಸಲಾಗಲಿಲ್ಲ: {exc}")
            st.rerun()
        else:
            ref = f" #{val(result, 'id')}" if val(result, "id") else ""
            # The booking is already saved. E-mail problems must never undo it.
            with st.spinner(L("Sending confirmation email...", "ದೃಢೀಕರಣ ಇಮೇಲ್ ಕಳುಹಿಸಲಾಗುತ್ತಿದೆ...",
                              "पुष्टि ईमेल भेजा जा रहा है...")):
                mail_ok, mail_info = send_booking_confirmation(val(result, "id"))
            if mail_ok:
                flash("success", L(f"Booking{ref} confirmed. Details sent to {mail_info}. Check 'My Bookings' for status.",
                                   f"ಬುಕ್ಕಿಂಗ್{ref} ಯಶಸ್ವಿಯಾಗಿದೆ. ವಿವರಗಳನ್ನು {mail_info} ಗೆ ಕಳುಹಿಸಲಾಗಿದೆ. ಸ್ಥಿತಿಗಾಗಿ 'ನನ್ನ ಬುಕ್ಕಿಂಗ್‌ಗಳು' ನೋಡಿ.",
                                   f"बुकिंग{ref} सफल रही। विवरण {mail_info} पर भेज दिया गया है। स्थिति के लिए 'मेरी बुकिंग' देखें।"))
            else:
                flash("warning", L(f"Booking{ref} confirmed, but the confirmation email could not be sent ({mail_info}). Your booking is safe - see 'My Bookings'.",
                                   f"ಬುಕ್ಕಿಂಗ್{ref} ಯಶಸ್ವಿಯಾಗಿದೆ, ಆದರೆ ಇಮೇಲ್ ಕಳುಹಿಸಲಾಗಲಿಲ್ಲ ({mail_info}). ನಿಮ್ಮ ಬುಕ್ಕಿಂಗ್ ಸುರಕ್ಷಿತ - 'ನನ್ನ ಬುಕ್ಕಿಂಗ್‌ಗಳು' ನೋಡಿ.",
                                   f"बुकिंग{ref} सफल रही, लेकिन ईमेल नहीं भेजा जा सका ({mail_info})। आपकी बुकिंग सुरक्षित है - 'मेरी बुकिंग' देखें।"))
            st.rerun()


@live(10)
def _slot_panel(machine_id, booking_date, start, hours):
    """Auto-refreshing timeline of already-booked slots for the chosen machine and date."""
    st.markdown("#### 🗓️ " + L(f"Slots on {booking_date:%d %b %Y}", f"{booking_date:%d-%m-%Y} ರ ಸಮಯಗಳು",
                                f"{booking_date:%d-%m-%Y} के समय"))
    slots = call_service(get_booked_slots, machine_id, booking_date) or []
    check = call_service(check_slot, machine_id, booking_date, start, hours)
    s = _tfloat(start)
    st.markdown(timeline_html(slots, (s, s + int(hours), bool(check and check["ok"]))), unsafe_allow_html=True)
    st.markdown(timeline_legend(), unsafe_allow_html=True)
    if slots:
        show_records([{
            "Booking ID": r["Booking ID"], "Date": r["Date"], "Start": r["Start"][:5], "End": r["End"][:5],
            "Hours": r["Hours"], "Status": r["Status"]} for r in slots])
        st.caption(L("A new booking may start exactly when another one ends.",
                     "ಒಂದು ಬುಕ್ಕಿಂಗ್ ಮುಗಿಯುವ ಕ್ಷಣದಲ್ಲೇ ಇನ್ನೊಂದನ್ನು ಆರಂಭಿಸಬಹುದು.",
                     "एक बुकिंग जिस समय खत्म हो, उसी समय नई बुकिंग शुरू हो सकती है।"))
    else:
        st.success(L("No bookings on this date — the whole day is free.",
                     "ಈ ದಿನಾಂಕದಲ್ಲಿ ಬುಕ್ಕಿಂಗ್ ಇಲ್ಲ — ಇಡೀ ದಿನ ಖಾಲಿ ಇದೆ.",
                     "इस तारीख पर कोई बुकिंग नहीं — पूरा दिन खाली है।"))


def _receipt_text(booking, bill):
    machine = val(booking, "machine")
    lines = [
        "KRISHI EQUIPMENT — RECEIPT", "-" * 34,
        f"Booking #{val(booking, 'id')}   Bill #{bill['bill_id']}",
        f"Equipment : {val(machine, 'name', '')}",
        f"Date      : {val(booking, 'booking_date')}  {val(booking, 'start_time')}",
        f"Hours used: {bill['hours_used']} x {money(bill['hourly_rate'])}",
        f"Bill      : {money(bill['amount'])}", f"Paid      : {money(bill['paid'])}",
        f"Pending   : {money(bill['due'])}", "-" * 34,
    ]
    for p in bill["payments"]:
        lines.append(f"{p['date']}  {money(p['amount'])}  {p['method']}  {p['reference']}".rstrip())
    return "\n".join(lines)


# =========================================================
# NEW: INVOICE / BILL EXPORT + UPI PAYMENT HELPERS
# Exports: PDF, Excel, CSV, printable HTML, plain text.
# Optional packages (the app still runs without them):
#   pip install reportlab openpyxl qrcode[pil]
# =========================================================
UPI_ID = os.getenv("UPI_ID", "").strip()
UPI_PAYEE_NAME = os.getenv("UPI_PAYEE_NAME", "").strip() or APP_NAME
HAS_REPORTLAB = find_spec("reportlab") is not None
HAS_OPENPYXL = find_spec("openpyxl") is not None
HAS_QRCODE = find_spec("qrcode") is not None


def rs(value):
    """Plain-text money (the PDF base fonts have no rupee glyph)."""
    try:
        return f"Rs. {float(value or 0):,.2f}"
    except (ValueError, TypeError):
        return "Rs. 0.00"


def invoice_title(inv):
    return "INVOICE" if inv["has_bill"] else "BOOKING SLIP (ESTIMATE - NOT BILLED YET)"


def _inv_time(inv):
    return f"{inv['start']:%H:%M} - {inv['end']:%H:%M}"


def invoice_fields(inv):
    """Ordered (label, value) pairs used by the CSV / Excel / text exports."""
    used = inv["hours_used"] if inv["has_bill"] else inv["booked_hours"]
    return [
        ("Invoice No", inv["invoice_no"]), ("Document", invoice_title(inv)),
        ("Bill Date", f"{inv['bill_date']:%Y-%m-%d}" if inv["bill_date"] else "-"),
        ("Booking ID", inv["booking_id"]), ("Booking Status", inv["status"]),
        ("Farmer", inv["farmer_name"]), ("Mobile", inv["farmer_phone"]), ("Email", inv["farmer_email"]),
        ("Equipment", inv["machine_name"]), ("Equipment ID", inv["machine_code"]),
        ("Work Date", str(inv["date"])), ("Time", _inv_time(inv)),
        ("Booked Hours", inv["booked_hours"]),
        ("Hours Billed" if inv["has_bill"] else "Hours (estimate)", used),
        ("Hourly Rate (INR)", f"{inv['hourly_rate']:.2f}"),
        ("Amount (INR)", f"{inv['amount']:.2f}"), ("Paid (INR)", f"{inv['paid']:.2f}"),
        ("Pending (INR)", f"{inv['due']:.2f}"), ("Payment Status", inv["payment_state"]),
        ("Notes", inv["notes"]),
    ]


def invoice_text(inv):
    line = "=" * 46
    out = [f"{APP_NAME.upper()}", invoice_title(inv), line]
    out += [f"{k:<18}: {v}" for k, v in invoice_fields(inv)]
    if inv["payments"]:
        out += ["-" * 46, "PAYMENTS RECEIVED"]
        out += [f"{p['date']}  {rs(p['amount']):>14}  {p['method']}  {p['reference']}".rstrip() for p in inv["payments"]]
    out += [line, "Thank you for using " + APP_NAME + "."]
    return "\n".join(out)


def invoice_csv(inv):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Field", "Value"])
    w.writerows(invoice_fields(inv))
    if inv["payments"]:
        w.writerow([])
        w.writerow(["Payment Date", "Amount (INR)", "Method", "Reference"])
        for p in inv["payments"]:
            w.writerow([p["date"], f"{p['amount']:.2f}", p["method"], p["reference"]])
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel shows Kannada/Hindi names correctly


def invoice_xlsx(inv):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(invoice_fields(inv), columns=["Field", "Value"]).astype(str).to_excel(xw, sheet_name="Invoice", index=False)
        pay = pd.DataFrame(inv["payments"], columns=["id", "date", "amount", "method", "reference"])
        pay.columns = ["Payment ID", "Date", "Amount (INR)", "Method", "Reference"]
        pay.to_excel(xw, sheet_name="Payments", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(
                    max(len(str(c.value or "")) for c in col) + 3, 48)
    return buf.getvalue()


def invoice_html(inv):
    """Stand-alone printable invoice. Open it in a browser and use Print -> Save as PDF."""
    e = esc
    used = inv["hours_used"] if inv["has_bill"] else inv["booked_hours"]
    pay_rows = "".join(
        f"<tr><td>{e(p['date'])}</td><td>{e(p['method'])}</td><td>{e(p['reference'])}</td>"
        f"<td class='r'>{e(rs(p['amount']))}</td></tr>" for p in inv["payments"])
    pay_block = (f"<h3>Payments received</h3><table><tr><th>Date</th><th>Method</th><th>Reference</th>"
                 f"<th class='r'>Amount</th></tr>{pay_rows}</table>") if pay_rows else ""
    colour = {"Paid": "#12673f", "Partial": "#8a5a00", "Unpaid": "#a02323"}.get(inv["payment_state"], "#254f9c")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{e(inv['invoice_no'])}</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;color:#172b25;margin:0;background:#f3f7f2}}
.page{{max-width:760px;margin:24px auto;background:#fff;border:1px solid #dbe8df;border-radius:14px;overflow:hidden}}
.head{{background:#176b45;color:#fff;padding:22px 28px}} .head h1{{margin:0;font-size:24px}} .head p{{margin:4px 0 0;opacity:.9}}
.body{{padding:24px 28px}} .grid{{display:flex;gap:24px;flex-wrap:wrap}} .grid>div{{flex:1;min-width:230px}}
h3{{margin:22px 0 8px;color:#176b45}} table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{background:#e5f5e9;text-align:left}} th,td{{padding:9px 10px;border-bottom:1px solid #e5ece7}} .r{{text-align:right}}
.tot td{{font-weight:700}} .state{{display:inline-block;padding:3px 12px;border-radius:99px;color:#fff;background:{colour};font-weight:700;font-size:13px}}
.foot{{padding:14px 28px;background:#f8faf8;color:#718071;font-size:12px}}
.btn{{display:block;margin:16px auto;padding:10px 22px;background:#176b45;color:#fff;border:0;border-radius:8px;font-size:15px;cursor:pointer}}
@media print{{body{{background:#fff}} .page{{border:0;margin:0}} .btn{{display:none}}}}
</style></head><body><div class="page">
<div class="head"><h1>{e(APP_NAME)}</h1><p>{e(invoice_title(inv))}</p></div>
<div class="body">
<div class="grid"><div><b>Billed to</b><br>{e(inv['farmer_name'])}<br>{e(inv['farmer_phone'])}<br>{e(inv['farmer_email'])}</div>
<div><b>Invoice no:</b> {e(inv['invoice_no'])}<br><b>Booking:</b> #{e(inv['booking_id'])} ({e(inv['status'])})<br>
<b>Bill date:</b> {e(f"{inv['bill_date']:%d %b %Y}" if inv['bill_date'] else '-')}<br><span class="state">{e(inv['payment_state'])}</span></div></div>
<h3>Service details</h3>
<table><tr><th>Equipment</th><th>Work date &amp; time</th><th class="r">Hours</th><th class="r">Rate/hour</th><th class="r">Amount</th></tr>
<tr><td>{e(inv['machine_name'])}<br><small>{e(inv['machine_code'])}</small></td><td>{e(inv['date'])}<br>{e(_inv_time(inv))}</td>
<td class="r">{e(used)}</td><td class="r">{e(rs(inv['hourly_rate']))}</td><td class="r">{e(rs(inv['amount']))}</td></tr></table>
<table style="margin-top:10px"><tr class="tot"><td class="r">Total</td><td class="r" style="width:150px">{e(rs(inv['amount']))}</td></tr>
<tr><td class="r">Paid</td><td class="r">{e(rs(inv['paid']))}</td></tr>
<tr class="tot"><td class="r">Balance due</td><td class="r">{e(rs(inv['due']))}</td></tr></table>
{pay_block}
{('<p><b>Notes:</b> ' + e(inv['notes']) + '</p>') if inv['notes'] else ''}
</div><div class="foot">Computer-generated document. Final bill = hours actually used x hourly rate.</div></div>
<button class="btn" onclick="window.print()">Print / Save as PDF</button></body></html>""".encode("utf-8")


def invoice_pdf(inv):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font, bold, unicode_ok = "Helvetica", "Helvetica-Bold", False
    font_path = os.getenv("PDF_FONT_PATH", "").strip()   # optional Unicode TTF (e.g. Noto Sans Kannada)
    if font_path and os.path.exists(font_path):
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            pdfmetrics.registerFont(TTFont("KEFont", font_path))
            font = bold = "KEFont"
            unicode_ok = True
        except Exception:
            pass

    def t(x):
        s = html.escape(str(x if x is not None else ""))
        return s if unicode_ok else s.encode("latin-1", "replace").decode("latin-1")

    green = colors.HexColor("#176b45")
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontName=font, fontSize=10, leading=14)
    right = ParagraphStyle("r", parent=body, alignment=2)
    head = ParagraphStyle("h", parent=body, fontName=bold, textColor=colors.white)
    head_r = ParagraphStyle("hr", parent=head, alignment=2)
    big = ParagraphStyle("big", parent=body, fontName=bold, fontSize=20, leading=24, textColor=green)
    sub = ParagraphStyle("sub", parent=body, fontName=bold, fontSize=11, textColor=colors.HexColor("#5c7168"))
    h3 = ParagraphStyle("h3", parent=body, fontName=bold, fontSize=11, textColor=green, spaceBefore=10, spaceAfter=4)

    used = inv["hours_used"] if inv["has_bill"] else inv["booked_hours"]
    P = lambda x, st=body: Paragraph(t(x), st)
    story = [P(APP_NAME, big), P(invoice_title(inv), sub), Spacer(1, 8)]

    meta = Table([[
        [P("Billed to", ParagraphStyle("x", parent=body, fontName=bold)), P(inv["farmer_name"]),
         P(inv["farmer_phone"]), P(inv["farmer_email"])],
        [P(f"Invoice no: {inv['invoice_no']}"), P(f"Booking: #{inv['booking_id']} ({inv['status']})"),
         P("Bill date: " + (f"{inv['bill_date']:%d %b %Y}" if inv["bill_date"] else "-")),
         P(f"Payment status: {inv['payment_state']}", ParagraphStyle("y", parent=body, fontName=bold))],
    ]], colWidths=[88 * mm, 86 * mm])
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.6, green),
                              ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 8),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [meta, Spacer(1, 10), P("Service details", h3)]

    items = Table([
        [P("Equipment", head), P("Work date / time", head), P("Hours", head_r), P("Rate / hour", head_r), P("Amount", head_r)],
        [P(f"{inv['machine_name']} ({inv['machine_code']})"), P(f"{inv['date']}  {_inv_time(inv)}"),
         P(used, right), P(rs(inv["hourly_rate"]), right), P(rs(inv["amount"]), right)],
    ], colWidths=[54 * mm, 42 * mm, 16 * mm, 30 * mm, 32 * mm])
    items.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), green), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfe3d6")),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [items, Spacer(1, 8)]

    bold_r = ParagraphStyle("br", parent=right, fontName=bold)
    totals = Table([[P("Total", bold_r), P(rs(inv["amount"]), bold_r)],
                    [P("Paid", right), P(rs(inv["paid"]), right)],
                    [P("Balance due", bold_r), P(rs(inv["due"]), bold_r)]], colWidths=[142 * mm, 32 * mm])
    totals.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.6, green), ("LINEABOVE", (0, 2), (-1, 2), 0.6, green)]))
    story.append(totals)

    if inv["payments"]:
        rows = [[P("Date", head), P("Method", head), P("Reference", head), P("Amount", head_r)]]
        rows += [[P(p["date"]), P(p["method"]), P(p["reference"] or "-"), P(rs(p["amount"]), right)] for p in inv["payments"]]
        pt = Table(rows, colWidths=[34 * mm, 38 * mm, 68 * mm, 34 * mm])
        pt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), green), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfe3d6"))]))
        story += [P("Payments received", h3), pt]
    if inv["notes"]:
        story += [Spacer(1, 8), P("Notes: " + inv["notes"])]
    story += [Spacer(1, 16), P("Computer-generated document. Final bill = hours actually used x hourly rate.",
                                ParagraphStyle("f", parent=body, fontSize=8, textColor=colors.grey))]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                      bottomMargin=16 * mm, title=inv["invoice_no"]).build(story)
    return buf.getvalue()


def _export_formats():
    fmts = {}
    if HAS_REPORTLAB:
        fmts["PDF"] = ("pdf", "application/pdf", invoice_pdf)
    if HAS_OPENPYXL:
        fmts["Excel (.xlsx)"] = ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", invoice_xlsx)
    fmts["CSV"] = ("csv", "text/csv", invoice_csv)
    fmts["Printable HTML"] = ("html", "text/html", invoice_html)
    fmts["Text"] = ("txt", "text/plain", lambda i: invoice_text(i).encode("utf-8"))
    return fmts


def export_widget(inv, key):
    """Format picker + one download button for a single booking / bill."""
    fmts = _export_formats()
    c1, c2 = st.columns([2, 2])
    with c1:
        choice = st.selectbox(L("Export format", "ಫೈಲ್ ಫಾರ್ಮ್ಯಾಟ್", "फ़ाइल प्रारूप"), list(fmts),
                              key=f"{key}_fmt")
    ext, mime, builder = fmts[choice]
    label = L("Download bill", "ಬಿಲ್ ಡೌನ್‌ಲೋಡ್", "बिल डाउनलोड") if inv["has_bill"] else \
        L("Download booking slip", "ಬುಕ್ಕಿಂಗ್ ಸ್ಲಿಪ್ ಡೌನ್‌ಲೋಡ್", "बुकिंग स्लिप डाउनलोड")
    with c2:
        st.write("")
        try:
            st.download_button("⬇️ " + label, data=builder(inv), file_name=f"{inv['invoice_no']}.{ext}",
                               mime=mime, key=f"{key}_dl", use_container_width=True)
        except Exception as exc:
            st.error(f"Could not build {choice}: {exc}")
    if not HAS_REPORTLAB or not HAS_OPENPYXL:
        st.caption("ℹ️ " + L("For PDF / Excel export run: pip install reportlab openpyxl",
                             "PDF / Excel ಗಾಗಿ ಚಾಲನೆ ಮಾಡಿ: pip install reportlab openpyxl",
                             "PDF / Excel के लिए चलाएँ: pip install reportlab openpyxl"))


def invoices_dataframe(invoices):
    rows = []
    for inv in invoices:
        rows.append({
            "Invoice No": inv["invoice_no"], "Booking ID": inv["booking_id"], "Farmer": inv["farmer_name"],
            "Equipment": inv["machine_name"], "Date": str(inv["date"]), "Time": _inv_time(inv),
            "Booked Hours": inv["booked_hours"], "Hours Billed": inv["hours_used"] if inv["has_bill"] else None,
            "Rate (INR)": inv["hourly_rate"], "Amount (INR)": inv["amount"] if inv["has_bill"] else None,
            "Paid (INR)": inv["paid"], "Pending (INR)": inv["due"], "Booking Status": inv["status"],
            "Payment Status": inv["payment_state"],
        })
    return pd.DataFrame(rows)


def bulk_export(df, base_name, key):
    """CSV / Excel download of any table."""
    if df is None or df.empty:
        st.info(L("Nothing to export yet.", "ಎಕ್ಸ್‌ಪೋರ್ಟ್ ಮಾಡಲು ಇನ್ನೂ ಏನೂ ಇಲ್ಲ.", "निर्यात के लिए अभी कुछ नहीं।"))
        return
    options = ["CSV"] + (["Excel (.xlsx)"] if HAS_OPENPYXL else [])
    c1, c2 = st.columns(2)
    with c1:
        choice = st.selectbox(L("Export format", "ಫೈಲ್ ಫಾರ್ಮ್ಯಾಟ್", "फ़ाइल प्रारूप"), options, key=f"{key}_bfmt")
    with c2:
        st.write("")
        if choice == "CSV":
            st.download_button("⬇️ " + tr("Download CSV"), df.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"{base_name}.csv", mime="text/csv", key=f"{key}_bdl", use_container_width=True)
        else:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as xw:
                df.to_excel(xw, sheet_name="Data", index=False)
            st.download_button("⬇️ Excel", buf.getvalue(), file_name=f"{base_name}.xlsx", key=f"{key}_bdl",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True)


def upi_link(amount, note):
    return (f"upi://pay?pa={_urlquote(UPI_ID, safe='@')}&pn={_urlquote(UPI_PAYEE_NAME)}"
            f"&am={float(amount):.2f}&cu=INR&tn={_urlquote(note)}")


@st.cache_data(show_spinner=False, max_entries=64)
def _qr_png(data):
    try:
        import qrcode
        img = qrcode.make(data)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def upi_panel(amount, note):
    """UPI QR for the pending amount. Set UPI_ID (and optionally UPI_PAYEE_NAME) in .env."""
    if not UPI_ID:
        st.info(L("Online (UPI) payment is not set up yet. Pay the owner directly - the payment is then recorded here.",
                  "ಆನ್‌ಲೈನ್ (UPI) ಪಾವತಿ ಇನ್ನೂ ಸಿದ್ಧವಾಗಿಲ್ಲ. ಮಾಲೀಕರಿಗೆ ನೇರವಾಗಿ ಪಾವತಿಸಿ - ನಂತರ ಇಲ್ಲಿ ದಾಖಲಾಗುತ್ತದೆ.",
                  "ऑनलाइन (UPI) भुगतान अभी सेट नहीं है। मालिक को सीधे भुगतान करें - फिर यहाँ दर्ज होगा।")
                + "  \n_(Admin: add `UPI_ID=yourname@bank` to `.env`)_")
        return
    link = upi_link(amount, note)
    png = _qr_png(link)
    c1, c2 = st.columns([1, 2])
    with c1:
        if png:
            st.image(png, width=190)
        else:
            st.caption("Install `qrcode[pil]` to show a scannable QR code.")
    with c2:
        st.markdown(f"**UPI ID:** `{UPI_ID}`")
        st.markdown(f"**{L('Amount', 'ಮೊತ್ತ', 'राशि')}:** {money(amount)}")
        st.caption(L("Scan with any UPI app (PhonePe, Google Pay, Paytm...). After paying, the admin records your payment and your bill turns Paid.",
                     "ಯಾವುದೇ UPI ಆ್ಯಪ್‌ನಿಂದ ಸ್ಕ್ಯಾನ್ ಮಾಡಿ. ಪಾವತಿಯ ನಂತರ ಆಡ್ಮಿನ್ ದಾಖಲಿಸುತ್ತಾರೆ, ನಿಮ್ಮ ಬಿಲ್ 'ಪಾವತಿಸಲಾಗಿದೆ' ಆಗುತ್ತದೆ.",
                     "किसी भी UPI ऐप से स्कैन करें। भुगतान के बाद एडमिन उसे दर्ज करेगा और आपका बिल 'भुगतान हो गया' दिखेगा।"))
        if not png:
            st.code(link)


def payment_form(bill_id, due, key, note=""):
    """Record a payment (cash / UPI / bank ...) against a bill. Used by Payments and Billing pages."""
    due = round(float(due), 2)
    k = f"{key}_{int(round(due * 100))}"          # key changes when the due amount changes
    amount = st.number_input(tr("Payment Amount (₹)"), min_value=0.01, max_value=max(due, 0.01),
                             value=max(due, 0.01), step=50.0, key=f"{k}_amt")
    method = st.selectbox(tr("Payment Method"), ["Cash", "UPI", "Bank Transfer", "Cheque", "Other"], key=f"{k}_method")
    if method == "UPI":
        upi_panel(amount, note or f"Bill {bill_id}")
    reference = st.text_input(tr("Reference (optional)"), key=f"{k}_ref",
                              placeholder=L("UPI transaction ID / cheque no.", "UPI ಟ್ರಾನ್ಸ್‌ಕ್ಷನ್ ID / ಚೆಕ್ ಸಂಖ್ಯೆ", "UPI लेन-देन ID / चेक नंबर"))
    if st.button("💾 " + tr("Record Payment"), type="primary", key=f"{k}_save", use_container_width=True):
        user = st.session_state.current_user
        if call_service(record_payment, bill_id, amount, method, reference.strip(), user["id"]) is not None:
            flash("success", L(f"Payment of {money(amount)} recorded.", f"{money(amount)} ಪಾವತಿ ದಾಖಲಾಗಿದೆ.",
                               f"{money(amount)} का भुगतान दर्ज हुआ।"))
            st.rerun()


def staff_bill_panel(booking_id, key):
    """Everything an admin/manager needs for ONE booking: generate bill, export, adjust hours, collect payment."""
    inv = call_service(get_invoice, booking_id)
    if inv is None:
        return
    today = date.today()
    st.markdown(f"##### 🧾 {L('Bill for Booking', 'ಬುಕ್ಕಿಂಗ್ ಬಿಲ್', 'बुकिंग का बिल')} #{inv['booking_id']} · "
                f"{esc(inv['machine_name'])} · {esc(inv['farmer_name'])}", unsafe_allow_html=True)

    if not inv["has_bill"]:
        if inv["status"] == "Cancelled":
            st.warning(L("A cancelled booking cannot be billed.", "ರದ್ದಾದ ಬುಕ್ಕಿಂಗ್‌ಗೆ ಬಿಲ್ ಮಾಡಲಾಗುವುದಿಲ್ಲ.", "रद्द बुकिंग का बिल नहीं बन सकता।"))
        elif inv["date"] > today:
            st.info(L(f"This work is on {inv['date']}. A bill can be generated on or after that date.",
                      f"ಈ ಕೆಲಸ {inv['date']} ರಂದು. ಆ ದಿನಾಂಕ ಅಥವಾ ನಂತರ ಬಿಲ್ ಮಾಡಬಹುದು.",
                      f"यह काम {inv['date']} को है। उस तारीख या उसके बाद बिल बन सकता है।"))
        else:
            hours = st.number_input(tr("Actual Usage Hours"), min_value=0.25, max_value=24.0,
                                    value=float(inv["booked_hours"]), step=0.25, key=f"{key}_hrs")
            st.metric(tr("Bill amount (actual hours × rate)"), money(hours * inv["hourly_rate"]))
            st.caption(f"{hours} h × {money(inv['hourly_rate'])}  ·  " + L(
                "Bill uses the hours actually worked, not the booked hours.",
                "ಬಿಲ್ ನಿಜವಾಗಿ ಕೆಲಸ ಮಾಡಿದ ಗಂಟೆಗಳ ಆಧಾರದ ಮೇಲೆ.", "बिल वास्तविक काम के घंटों पर आधारित है।"))
            if st.button("🧾 " + tr("Create Bill"), type="primary", key=f"{key}_mk", use_container_width=True):
                if call_service(create_bill, inv["booking_id"], hours) is not None:
                    flash("success", tr("Bill created."))
                    st.rerun()
        with st.expander("📤 " + L("Export booking slip", "ಬುಕ್ಕಿಂಗ್ ಸ್ಲಿಪ್ ಎಕ್ಸ್‌ಪೋರ್ಟ್", "बुकिंग स्लिप निर्यात")):
            export_widget(inv, f"{key}_ex")
        return

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(L("Hours used", "ಬಳಸಿದ ಗಂಟೆ", "उपयोग घंटे"), inv["hours_used"])
    k2.metric(L("Bill amount", "ಬಿಲ್ ಮೊತ್ತ", "बिल राशि"), money(inv["amount"]))
    k3.metric(L("Paid", "ಪಾವತಿಸಿದ್ದು", "भुगतान किया"), money(inv["paid"]))
    k4.metric(L("Pending", "ಬಾಕಿ", "बकाया"), money(inv["due"]))
    st.markdown(badge(inv["payment_state"]), unsafe_allow_html=True)

    with st.expander("📤 " + L("Export bill", "ಬಿಲ್ ಎಕ್ಸ್‌ಪೋರ್ಟ್", "बिल निर्यात"), expanded=True):
        export_widget(inv, f"{key}_ex")
    if inv["due"] > 0:
        with st.expander("💳 " + L("Collect payment", "ಪಾವತಿ ಸಂಗ್ರಹಿಸಿ", "भुगतान लें"), expanded=True):
            payment_form(inv["bill_id"], inv["due"], f"{key}_pay", f"Bill {inv['invoice_no']}")
    if not inv["payments"]:
        with st.expander("✏️ " + L("Correct hours (only before any payment)", "ಗಂಟೆ ತಿದ್ದಿ (ಪಾವತಿಗೆ ಮೊದಲು ಮಾತ್ರ)",
                                   "घंटे सुधारें (भुगतान से पहले ही)")):
            new_hours = st.number_input(tr("Actual Usage Hours"), min_value=0.25, max_value=24.0,
                                        value=float(inv["hours_used"]), step=0.25, key=f"{key}_adj")
            if st.button(L("Update bill hours", "ಬಿಲ್ ಗಂಟೆ ನವೀಕರಿಸಿ", "बिल के घंटे अपडेट करें"), key=f"{key}_adjbtn"):
                if call_service(adjust_bill_hours, inv["bill_id"], new_hours) is not None:
                    flash("success", L("Bill updated.", "ಬಿಲ್ ನವೀಕರಿಸಲಾಗಿದೆ.", "बिल अपडेट हुआ।"))
                    st.rerun()
    else:
        with st.expander(L("Payment history", "ಪಾವತಿ ಇತಿಹಾಸ", "भुगतान इतिहास")):
            show_records([{"Date": p["date"], "Amount": money(p["amount"]), "Method": p["method"],
                           "Reference": p["reference"]} for p in inv["payments"]])


def farmer_my_bookings():
    user = st.session_state.current_user
    st.title("📦 " + tr("My Bookings"))

    bookings = call_service(get_farmer_bookings, user["id"])
    if not bookings:
        st.info(tr("ಇನ್ನೂ bookings ಇಲ್ಲ."))
        return
    invoices = call_service(get_farmer_invoices, user["id"]) or {}
    billed_list = [i for i in invoices.values() if i["has_bill"]]

    billed = sum(i["amount"] for i in billed_list)
    paid = sum(i["paid"] for i in billed_list)
    m1, m2, m3 = st.columns(3)
    m1.metric(L("Total billed", "ಒಟ್ಟು ಬಿಲ್", "कुल बिल"), money(billed))
    m2.metric(L("Paid", "ಪಾವತಿಸಿದ್ದು", "भुगतान किया"), money(paid))
    m3.metric(L("Pending", "ಬಾಕಿ", "बकाया"), money(billed - paid))

    with st.expander("📤 " + L("Export all my bookings & bills", "ನನ್ನ ಎಲ್ಲಾ ಬುಕ್ಕಿಂಗ್/ಬಿಲ್ ಎಕ್ಸ್‌ಪೋರ್ಟ್",
                              "मेरी सभी बुकिंग/बिल निर्यात करें")):
        bulk_export(invoices_dataframe(sorted(invoices.values(), key=lambda i: (i["date"], i["start"]), reverse=True)),
                    f"my_bookings_{date.today():%Y%m%d}", "mb_all")

    f1, f2 = st.columns([2, 2])
    with f1:
        chosen = st.selectbox(tr("Status"), ["All", "Confirmed", "In Progress", "Completed", "Cancelled"],
                              format_func=lambda x: L("All", "ಎಲ್ಲವೂ", "सभी") if x == "All" else tr(x), key="mb_filter")
    with f2:
        bill_filter = st.selectbox(L("Bill", "ಬಿಲ್", "बिल"), ["All", "Not billed", "Unpaid / Partial", "Paid"],
                                   format_func=lambda x: {"All": L("All", "ಎಲ್ಲವೂ", "सभी"),
                                                          "Not billed": L("Not billed yet", "ಇನ್ನೂ ಬಿಲ್ ಆಗಿಲ್ಲ", "अभी बिल नहीं बना"),
                                                          "Unpaid / Partial": L("Payment pending", "ಪಾವತಿ ಬಾಕಿ", "भुगतान बाकी"),
                                                          "Paid": tr("Paid")}[x], key="mb_bill_filter")

    shown = 0
    for booking in bookings:
        bid = val(booking, "id")
        inv = invoices.get(bid)
        if inv is None:
            continue
        if chosen != "All" and inv["status"] != chosen:
            continue
        if bill_filter == "Not billed" and inv["has_bill"]:
            continue
        if bill_filter == "Unpaid / Partial" and inv["payment_state"] not in ("Unpaid", "Partial"):
            continue
        if bill_filter == "Paid" and inv["payment_state"] != "Paid":
            continue
        shown += 1

        with st.container(border=True):
            top_l, top_r = st.columns([3, 1])
            with top_l:
                st.subheader(f"Booking #{bid}")
            with top_r:
                st.markdown(badge(inv["status"]), unsafe_allow_html=True)

            d1, d2 = st.columns(2)
            with d1:
                st.write(f"🚜 **{L('Equipment', 'ಯಂತ್ರ', 'उपकरण')}:** {inv['machine_name']} ({inv['machine_code']})")
                st.write(f"📅 **{L('Date', 'ದಿನಾಂಕ', 'तारीख')}:** {inv['date']}")
            with d2:
                st.write(f"⏰ **{L('Time', 'ಸಮಯ', 'समय')}:** {inv['start']:%H:%M} – {inv['end']:%H:%M}")
                st.write(f"⌛ **{L('Hours booked', 'ಬುಕ್ ಮಾಡಿದ ಗಂಟೆ', 'बुक किए घंटे')}:** {inv['booked_hours']}")
            if inv["notes"]:
                st.caption(f"📝 {inv['notes']}")

            # ---------- bill section ----------
            if inv["has_bill"]:
                st.markdown(f"**🧾 {L('Bill', 'ಬಿಲ್', 'बिल')} {inv['invoice_no']}** &nbsp; {badge(inv['payment_state'])}",
                            unsafe_allow_html=True)
                b1, b2, b3, b4 = st.columns(4)
                b1.metric(L("Hours used", "ಬಳಸಿದ ಗಂಟೆ", "उपयोग घंटे"), inv["hours_used"])
                b2.metric(L("Bill amount", "ಬಿಲ್ ಮೊತ್ತ", "बिल राशि"), money(inv["amount"]))
                b3.metric(L("Paid", "ಪಾವತಿಸಿದ್ದು", "भुगतान किया"), money(inv["paid"]))
                b4.metric(L("Pending", "ಬಾಕಿ", "बकाया"), money(inv["due"]))
                st.progress(min(max(inv["paid"] / inv["amount"], 0.0), 1.0) if inv["amount"] else 1.0)
                st.caption(f"{inv['hours_used']} h × {money(inv['hourly_rate'])} = {money(inv['amount'])}")
                if inv["payments"]:
                    with st.expander(L("Payment history", "ಪಾವತಿ ಇತಿಹಾಸ", "भुगतान इतिहास")):
                        show_records([{"Date": p["date"], "Amount": money(p["amount"]), "Method": p["method"],
                                       "Reference": p["reference"]} for p in inv["payments"]])
                if inv["due"] > 0:
                    with st.expander("💵 " + L(f"Pay {money(inv['due'])} by Cash", f"{money(inv['due'])} ನಗದು ಪಾವತಿಸಿ",
                                               f"{money(inv['due'])} नकद भुगतान करें"), expanded=True):
                        st.caption(L("Click the button to pay this bill by cash. The bill is marked Paid right away.",
                                     "ನಗದು ಮೂಲಕ ಈ ಬಿಲ್ ಪಾವತಿಸಲು ಬಟನ್ ಒತ್ತಿ. ಬಿಲ್ ತಕ್ಷಣ 'ಪಾವತಿಸಲಾಗಿದೆ' ಆಗುತ್ತದೆ.",
                                     "नकद में यह बिल चुकाने के लिए बटन दबाएं। बिल तुरंत 'भुगतान हो गया' हो जाएगा।"))
                        if st.button("💵 " + L("Pay Bill by Cash", "ನಗದು ಮೂಲಕ ಬಿಲ್ ಪಾವತಿಸಿ", "नकद में बिल चुकाएं"),
                                     key=f"paycash_{bid}_{int(round(inv['due'] * 100))}",
                                     type="primary", use_container_width=True):
                            if call_service(record_payment, inv["bill_id"], inv["due"], "Cash",
                                            "Paid by cash", user["id"]) is not None:
                                flash("success", L(f"Payment of {money(inv['due'])} received in cash. Bill {inv['invoice_no']} is now Paid.",
                                                   f"{money(inv['due'])} ನಗದು ಪಾವತಿ ದಾಖಲಾಗಿದೆ. ಬಿಲ್ {inv['invoice_no']} ಈಗ ಪಾವತಿಸಲಾಗಿದೆ.",
                                                   f"{money(inv['due'])} नकद भुगतान दर्ज हुआ। बिल {inv['invoice_no']} अब भुगतान हो गया।"))
                                st.rerun()
            elif inv["status"] != "Cancelled":
                est = inv["amount"]
                if inv["date"] <= date.today():
                    st.caption(L(f"Not billed yet. Bill will be {money(est)} ({inv['booked_hours']} h × {money(inv['hourly_rate'])}). "
                                 "If the actual hours were different, the admin can correct them.",
                                 f"ಇನ್ನೂ ಬಿಲ್ ಆಗಿಲ್ಲ. ಬಿಲ್ {money(est)} ({inv['booked_hours']} ಗಂ × {money(inv['hourly_rate'])}). "
                                 "ನಿಜವಾದ ಗಂಟೆ ಬೇರೆಯಾಗಿದ್ದರೆ ಆಡ್ಮಿನ್ ತಿದ್ದಬಹುದು.",
                                 f"अभी बिल नहीं बना। बिल {money(est)} ({inv['booked_hours']} घं × {money(inv['hourly_rate'])}) होगा। "
                                 "वास्तविक घंटे अलग हों तो एडमिन सुधार सकता है।"))
                    if st.button("🧾 " + L("Generate bill", "ಬಿಲ್ ರಚಿಸಿ", "बिल बनाएं"), key=f"genbill_{bid}",
                                 type="primary", use_container_width=True):
                        if call_service(create_bill_for_farmer, user["id"], bid) is not None:
                            flash("success", tr("Bill created."))
                            st.rerun()
                else:
                    st.caption(L(f"Estimated cost {money(est)}. You can generate the bill on or after {inv['date']}.",
                                 f"ಅಂದಾಜು ವೆಚ್ಚ {money(est)}. {inv['date']} ಅಥವಾ ನಂತರ ಬಿಲ್ ರಚಿಸಬಹುದು.",
                                 f"अनुमानित लागत {money(est)}। बिल {inv['date']} या उसके बाद बनाया जा सकता है।"))

            # ---------- export (this booking only) ----------
            if inv["status"] != "Cancelled" or inv["has_bill"]:
                with st.expander("📤 " + L("Export / Download", "ಎಕ್ಸ್‌ಪೋರ್ಟ್ / ಡೌನ್‌ಲೋಡ್", "निर्यात / डाउनलोड")):
                    export_widget(inv, f"mb_{bid}")

            if (not inv["has_bill"] and inv["status"] in ("Confirmed", "Approved")
                    and inv["date"] >= date.today()):
                if st.button("✖ " + L("Cancel booking", "ಬುಕ್ಕಿಂಗ್ ರದ್ದು", "बुकिंग रद्द करें"), key=f"cancel_{bid}"):
                    if call_service(cancel_booking, bid, user["id"]) is not None:
                        mail_ok, _info = send_booking_cancellation(bid)
                        flash("success", L("Booking cancelled." + (" Cancellation email sent." if mail_ok else ""),
                                           "ಬುಕ್ಕಿಂಗ್ ರದ್ದಾಗಿದೆ." + (" ರದ್ದತಿ ಇಮೇಲ್ ಕಳುಹಿಸಲಾಗಿದೆ." if mail_ok else ""),
                                           "बुकिंग रद्द कर दी गई।" + (" रद्दीकरण ईमेल भेजा गया।" if mail_ok else "")))
                        st.rerun()
    if shown == 0:
        st.info(L("No bookings match this filter.", "ಈ ಫಿಲ್ಟರ್‌ಗೆ ಹೊಂದುವ ಬುಕ್ಕಿಂಗ್ ಇಲ್ಲ.", "इस फ़िल्टर से कोई बुकिंग मेल नहीं खाती।"))


def farmer_dashboard(user):
    greeting = {"English": "Hello", "Kannada": "ನಮಸ್ಕಾರ", "Hindi": "नमस्ते"}.get(
        st.session_state.get("app_language", "English"), "Hello")
    hero(f"{greeting}, {user['full_name']} 👋", tr("Welcome to your farm equipment booking and billing service."))

    bookings = call_service(get_farmer_bookings, user["id"]) or []
    bills = call_service(get_farmer_bill_map, user["id"]) or {}
    total = len(bookings)
    active = sum(1 for b in bookings if str(val(b, "status", "")).lower() in ("pending", "confirmed", "in progress"))
    pending = sum(b["due"] for b in bills.values())
    m1, m2, m3 = st.columns(3)
    m1.metric(tr("Total Bookings"), total)
    m2.metric(L("Active", "ಸಕ್ರಿಯ", "सक्रिय"), active)
    m3.metric(L("Pending dues", "ಬಾಕಿ ಮೊತ್ತ", "बकाया राशि"), money(pending))

    if pending > 0:
        st.warning(L(f"You have {money(pending)} pending. See 'My Bookings' for each bill.",
                     f"ನಿಮಗೆ {money(pending)} ಬಾಕಿ ಇದೆ. ಪ್ರತಿ ಬಿಲ್‌ಗಾಗಿ 'ನನ್ನ ಬುಕ್ಕಿಂಗ್‌ಗಳು' ನೋಡಿ.",
                     f"आपका {money(pending)} बकाया है। प्रत्येक बिल के लिए 'मेरी बुकिंग' देखें।"))

    upcoming = sorted(
        [b for b in bookings if val(b, "status") in ("Confirmed", "Approved", "In Progress")
         and val(b, "booking_date") >= date.today()],
        key=lambda b: (val(b, "booking_date"), val(b, "start_time")))
    if upcoming:
        nb = upcoming[0]
        st.markdown(
            f'<div class="notice notice-info">⏭️ <b>{L("Next booking", "ಮುಂದಿನ ಬುಕ್ಕಿಂಗ್", "अगली बुकिंग")}:</b> '
            f'{esc(val(val(nb, "machine"), "name", ""))} · {esc(val(nb, "booking_date"))} · '
            f'{esc(str(val(nb, "start_time"))[:5])} · {esc(val(nb, "booked_hours"))} h</div>', unsafe_allow_html=True)

    st.markdown(f"#### {tr('Quick actions')}")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.button("🚜 Equipment ನೋಡಿ", use_container_width=True, on_click=set_farmer_nav, args=("Equipment Catalogue",))
    with c2:
        st.button("📅 Booking ಮಾಡಿ", use_container_width=True, on_click=set_farmer_nav, args=("Book Equipment",))
    with c3:
        st.button("🌦️ " + tr("Weather & AI"), use_container_width=True, on_click=set_farmer_nav, args=("Weather & AI",))
    c4, c5, _ = st.columns(3)
    with c4:
        st.button("📆 " + tr("Calendar"), use_container_width=True, on_click=set_farmer_nav, args=("Calendar",))
    with c5:
        st.button("📦 " + tr("My Bookings"), use_container_width=True, on_click=set_farmer_nav, args=("My Bookings",))


def _get_weather_by_coordinates(lat, lon):
    """Fetch current and forecast weather directly from coordinates.

    This avoids the fragile reverse-geocoding step that caused "city not found"
    for valid device/map coordinates. Open-Meteo does not require an API key.
    """
    import requests

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": float(lat),
        "longitude": float(lon),
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,showers,weather_code,wind_speed_10m,wind_direction_10m",
        "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,sunrise,sunset",
        "timezone": "auto",
        "forecast_days": 7,
    }
    response = requests.get(url, params=params, timeout=18)
    response.raise_for_status()
    data = response.json()
    current = data.get("current", {})
    code = current.get("weather_code")
    return {
        "source": "Open-Meteo",
        "timezone": data.get("timezone", "Local time"),
        "coordinates": {"latitude": lat, "longitude": lon},
        "current": {
            "temperature": current.get("temperature_2m"),
            "feels_like": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "wind_speed": current.get("wind_speed_10m"),
            "wind_direction": current.get("wind_direction_10m"),
            "precipitation": current.get("precipitation"),
            "description": WEATHER_CODES.get(code, "Current conditions"),
            "time": current.get("time"),
            "weather_code": code,
        },
        "hourly": data.get("hourly", {}),
        "daily": data.get("daily", {}),
    }


def _reverse_geocode(lat, lon):
    """Return a readable place name for map/device coordinates."""
    try:
        import requests
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 10},
            headers={"User-Agent": "KrishiEquipment/1.0 (weather location lookup)"},
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        address = data.get("address", {})
        return (
            address.get("city") or address.get("town") or
            address.get("village") or address.get("county") or
            address.get("state_district") or address.get("state") or
            data.get("display_name", "").split(",")[0]
        )
    except Exception:
        return ""


def _render_weather_result(result, location_name):
    """Render weather responses from integrations.py in a friendly dashboard."""
    if not result:
        st.warning("Weather information is not available for this location right now.")
        return

    if not isinstance(result, dict):
        st.info(str(result))
        return

    # Handle common weather API response keys without assuming a single schema.
    current = result.get("current", result.get("current_weather", result))
    if not isinstance(current, dict):
        current = result

    temp = current.get("temperature", current.get("temp", current.get("temperature_2m")))
    feels = current.get("feels_like", current.get("apparent_temperature"))
    humidity = current.get("humidity", current.get("relative_humidity_2m"))
    wind = current.get("wind_speed", current.get("windspeed", current.get("wind_speed_10m")))
    description = current.get("description", current.get("condition", current.get("weather", "Current conditions")))
    rain = current.get("precipitation", current.get("rain", current.get("precipitation_probability")))

    st.markdown(f"### 📍 {location_name or 'Selected location'}")
    st.caption("Weather snapshot · Check local conditions before operating machinery or spraying crops.")
    cards = st.columns(4)
    values = [
        ("🌡️ Temperature", temp, " °C"),
        ("💧 Humidity", humidity, " %"),
        ("💨 Wind speed", wind, " km/h"),
        ("🌧️ Rainfall", rain, " mm"),
    ]
    for col, (label, value, suffix) in zip(cards, values):
        with col:
            display = "—" if value is None else f"{value}{suffix}"
            st.metric(label, display)
    st.info(f"**Conditions:** {description}" + (f"  ·  Feels like {feels} °C" if feels is not None else ""))

    hourly = result.get("hourly", {})
    daily = result.get("daily", {})
    if isinstance(daily, dict) and daily.get("time"):
        st.markdown("#### 📅 7-day forecast")
        forecast_rows = []
        for i, day in enumerate(daily.get("time", [])[:7]):
            def at(key):
                values = daily.get(key, [])
                return values[i] if i < len(values) else None
            forecast_rows.append({
                "Date": day,
                "Condition": weather_label(at("weather_code")),
                "High (°C)": at("temperature_2m_max"),
                "Low (°C)": at("temperature_2m_min"),
                "Rain chance (%)": at("precipitation_probability_max"),
                "Rain (mm)": at("precipitation_sum"),
            })
        st.dataframe(pd.DataFrame(forecast_rows), use_container_width=True, hide_index=True)
    if isinstance(hourly, dict) and hourly.get("time"):
        with st.expander("Next 12 hours"):
            rows = []
            for i, hour in enumerate(hourly.get("time", [])[:12]):
                temps = hourly.get("temperature_2m", [])
                rains = hourly.get("precipitation_probability", [])
                rows.append({
                    "Time": hour,
                    "Temperature (°C)": temps[i] if i < len(temps) else None,
                    "Rain chance (%)": rains[i] if i < len(rains) else None,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption(f"Weather source: {result.get('source', 'configured weather provider')}. Forecasts are estimates; verify local conditions before farm operations.")
    with st.expander("View complete weather data"):
        st.json(result)


def farmer_ai_weather():
    st.title("🌦️ " + tr("Weather & AI"))
    st.caption("Location-aware weather and agriculture guidance for better farm decisions.")
    weather_tab, ai_tab = st.tabs(["🌤️ Weather & Location", "🤖 " + tr("AI Assistant")])

    with weather_tab:
        st.markdown("#### Find weather for your farm")
        st.write("Choose a location by typing a place name, using your device location, or selecting a point on the map.")

        location_mode = st.radio(
            "Choose location method",
            ["Search by place name", "Use my device location", "Select on map"],
            horizontal=True,
            key="weather_location_mode",
        )
        city = ""
        selected_lat = None
        selected_lon = None

        if location_mode == "Search by place name":
            c1, c2 = st.columns([3, 1])
            with c1:
                city = st.text_input(
                    "City / Town / Village",
                    placeholder="e.g. Nanjangud, Mysuru, Gundlupet",
                    key="weather_city_search",
                ).strip()
            with c2:
                st.write("")
                st.write("")
                find_weather = st.button("Get weather", type="primary", use_container_width=True, key="weather_search_btn")
            st.caption("Tip: enter the nearest town or village for more relevant local weather.")
            if find_weather:
                if len(city) < 2:
                    st.error("Enter a valid place name.")
                else:
                    with st.spinner(f"Loading weather for {city}..."):
                        result = call_service(get_weather, city)
                    if result:
                        st.session_state.weather_last_result = result
                        st.session_state.weather_last_location = city

        elif location_mode == "Use my device location":
            st.info("Your browser may ask for location permission. Your location is used only to look up weather in this session.")
            try:
                from streamlit_geolocation import streamlit_geolocation
                geo = streamlit_geolocation()
            except ImportError:
                geo = None
                st.warning("Device location needs the optional package. In your terminal run: pip install streamlit-geolocation")
                st.caption("Or switch to 'Search by place name' or 'Select on map'.")

            if isinstance(geo, dict) and geo.get("latitude") is not None and geo.get("longitude") is not None:
                selected_lat = float(geo["latitude"])
                selected_lon = float(geo["longitude"])
                st.success(f"Location detected: {selected_lat:.5f}, {selected_lon:.5f}")
                if st.button("Get weather at my location", type="primary", key="weather_device_btn"):
                    with st.spinner("Loading live weather for your coordinates..."):
                        result = call_service(_get_weather_by_coordinates, selected_lat, selected_lon)
                        if result:
                            place_label = _reverse_geocode(selected_lat, selected_lon)
                            st.session_state.weather_last_result = result
                            st.session_state.weather_last_location = f"{place_label or 'Your device location'} ({selected_lat:.4f}, {selected_lon:.4f})"
            else:
                st.caption("If permission is denied or no location appears, use the place-name search instead.")

        else:
            st.markdown("##### Click a point on the map")
            st.caption("Map selection requires the optional `folium` and `streamlit-folium` packages.")
            try:
                import folium
                from streamlit_folium import st_folium
                default_lat = float(st.session_state.get("weather_map_lat", 12.2958))
                default_lon = float(st.session_state.get("weather_map_lon", 76.6394))
                fmap = folium.Map(location=[default_lat, default_lon], zoom_start=8, control_scale=True)
                folium.Marker([default_lat, default_lon], tooltip="Selected point", icon=folium.Icon(color="green")).add_to(fmap)
                map_result = st_folium(fmap, height=380, width=None, returned_objects=["last_clicked"])
                clicked = map_result.get("last_clicked") if isinstance(map_result, dict) else None
                if clicked:
                    selected_lat = float(clicked["lat"])
                    selected_lon = float(clicked["lng"])
                    st.session_state.weather_map_lat = selected_lat
                    st.session_state.weather_map_lon = selected_lon
                    st.success(f"Selected coordinates: {selected_lat:.5f}, {selected_lon:.5f}")
                elif st.session_state.get("weather_map_lat") is not None:
                    selected_lat = float(st.session_state.weather_map_lat)
                    selected_lon = float(st.session_state.weather_map_lon)
                if st.button("Get weather for selected map point", type="primary", key="weather_map_btn"):
                    if selected_lat is None or selected_lon is None:
                        st.error("Click a location on the map first.")
                    else:
                        with st.spinner("Loading weather for the selected map point..."):
                            result = call_service(_get_weather_by_coordinates, selected_lat, selected_lon)
                            if result:
                                place_label = _reverse_geocode(selected_lat, selected_lon)
                                st.session_state.weather_last_result = result
                                st.session_state.weather_last_location = f"{place_label or 'Selected map point'} ({selected_lat:.4f}, {selected_lon:.4f})"
            except ImportError:
                st.warning("Map selection needs optional packages. In your terminal run: pip install folium streamlit-folium")
                st.caption("After installation, restart Streamlit. You can use place-name search immediately.")

        if st.session_state.get("weather_last_result"):
            st.divider()
            _render_weather_result(
                st.session_state.weather_last_result,
                st.session_state.get("weather_last_location", "Selected location"),
            )

        st.markdown("#### 🌾 Farm-friendly weather checklist")
        tips = st.columns(3)
        with tips[0]:
            with st.container(border=True):
                st.markdown("**🌧️ Before rain**")
                st.write("Review rainfall outlook before irrigation, fertilizer application, or harvesting.")
        with tips[1]:
            with st.container(border=True):
                st.markdown("**💨 During strong wind**")
                st.write("Avoid spraying when wind may carry chemicals away from the target crop.")
        with tips[2]:
            with st.container(border=True):
                st.markdown("**🚜 Equipment planning**")
                st.write("Plan field work around wet soil, rain, visibility, and safe operating conditions.")
        st.caption("Weather data may be delayed or approximate. Follow local agricultural advisories and equipment safety instructions.")

    with ai_tab:
        st.markdown("#### Ask a farming question")
        language = st.selectbox(tr("Answer Language"), ["Kannada", "English", "Hindi"], format_func=lambda x: LANGUAGES[x], key="weather_ai_language")
        question = st.text_area("Your question", placeholder="e.g. What should I consider before using a rotavator after heavy rain?", height=130)
        if st.button("✨ " + tr("Ask AI"), type="primary", key="weather_ai_submit"):
            if not question.strip():
                st.error("Please enter your question.")
            else:
                with st.spinner("Preparing your answer..."):
                    answer = call_service(ask_agriculture_ai, question.strip(), language)
                if answer:
                    st.markdown("### Answer")
                    st.markdown(answer)


# =========================================================
# MANAGER PAGES
# =========================================================

@st.cache_data(ttl=15, show_spinner=False)
def _cached_service_overview():
    return get_service_overview()


def _service_lines(rows, level):
    return [f"{r['name']} ({r['machine_code']}) — {r['hours_since_service']:.0f} h" for r in rows if r["service_level"] == level]


def staff_service_banner():
    """Shown on every admin/manager page: reminder when a machine reaches 100 worked hours."""
    try:
        rows = _cached_service_overview()
    except Exception:
        return
    due, soon = _service_lines(rows, "due"), _service_lines(rows, "soon")
    if due:
        st.error("🔧 " + L("Service required (100+ hours since last service): ",
                           "ಸೇವೆ ಅಗತ್ಯ (ಕೊನೆಯ ಸೇವೆಯ ನಂತರ 100+ ಗಂಟೆ): ",
                           "सर्विस जरूरी (पिछली सर्विस के बाद 100+ घंटे): ") + "; ".join(due))
    if soon:
        st.warning("⚠️ " + L("Service due soon (90+ hours): ", "ಶೀಘ್ರದಲ್ಲೇ ಸೇವೆ ಬೇಕು (90+ ಗಂಟೆ): ",
                             "जल्द सर्विस चाहिए (90+ घंटे): ") + "; ".join(soon))


def _greeting():
    return {"English": "Hello", "Kannada": "ನಮಸ್ಕಾರ", "Hindi": "नमस्ते"}.get(
        st.session_state.get("app_language", "English"), "Hello")


def admin_overview():
    user = st.session_state.current_user
    hero(f"{_greeting()}, {user['full_name']} 👋",
         L("Live overview of equipment, bookings, dues and service reminders.",
           "ಯಂತ್ರ, ಬುಕ್ಕಿಂಗ್, ಬಾಕಿ ಮತ್ತು ಸೇವಾ ಜ್ಞಾಪನೆಗಳ ನೇರ ಅವಲೋಕನ.",
           "उपकरण, बुकिंग, बकाया और सर्विस रिमाइंडर का लाइव अवलोकन।"))
    _admin_overview_live()


@live(20)
def _admin_overview_live():
    data = call_service(get_admin_overview)
    if data is None:
        return
    r1 = st.columns(3)
    r1[0].metric("🚜 " + L("Equipment", "ಯಂತ್ರಗಳು", "उपकरण"), data["machines"])
    r1[1].metric("📋 " + L("Active bookings", "ಸಕ್ರಿಯ ಬುಕ್ಕಿಂಗ್", "सक्रिय बुकिंग"), data["active_bookings"])
    r1[2].metric("🔧 " + tr("Under Service"), data["under_service"])
    r2 = st.columns(3)
    r2[0].metric("🕒 " + L("Pending approvals", "ಬಾಕಿ ಅನುಮೋದನೆ", "लंबित अनुमोदन"), data["pending_approvals"])
    r2[1].metric("💰 " + L("Collected this month", "ಈ ತಿಂಗಳ ಸಂಗ್ರಹ", "इस माह की वसूली"), money(data["collected_month"]))
    r2[2].metric("⏳ " + tr("Outstanding Due"), money(data["outstanding"]))

    st.markdown("#### 🔧 " + L("Service reminders (every 100 worked hours)", "ಸೇವಾ ಜ್ಞಾಪನೆಗಳು (ಪ್ರತಿ 100 ಕೆಲಸದ ಗಂಟೆಗೆ)",
                                "सर्विस रिमाइंडर (हर 100 कार्य-घंटे पर)"))
    rows = call_service(get_service_overview) or []
    flagged = [r for r in rows if r["service_level"] != "ok"]
    if not flagged:
        st.markdown(f'<div class="notice notice-good">✅ {L("All equipment is within its service limit.", "ಎಲ್ಲಾ ಯಂತ್ರಗಳು ಸೇವಾ ಮಿತಿಯೊಳಗಿವೆ.", "सभी उपकरण सर्विस सीमा के भीतर हैं।")}</div>',
                    unsafe_allow_html=True)
    for r in flagged:
        due = r["service_level"] == "due"
        cls = "notice-bad" if due else "notice-warn"
        label = (L("SERVICE REQUIRED", "ಸೇವೆ ಅಗತ್ಯ", "सर्विस जरूरी") if due
                 else L("Service due soon", "ಶೀಘ್ರದಲ್ಲೇ ಸೇವೆ", "जल्द सर्विस"))
        st.markdown(
            f'<div class="notice {cls}">{"🔴" if due else "🟠"} <b>{esc(r["name"])}</b> ({esc(r["machine_code"])}) — '
            f'{r["hours_since_service"]:.0f} / {SERVICE_INTERVAL_HOURS} h · {label}</div>', unsafe_allow_html=True)
    if flagged and st.button("🔧 " + tr("Equipment Service Status"), key="ov_goto_service"):
        st.session_state._nav_request = "Equipment Service Status"
        st.rerun()

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### 📊 " + L("Most used machines (hours used)", "ಅತಿ ಹೆಚ್ಚು ಬಳಸಿದ ಯಂತ್ರಗಳು (ಗಂಟೆ)", "सबसे ज्यादा उपयोग किए गए उपकरण (घंटे)"))
        usage = call_service(get_machine_usage) or []
        if usage and any(u["Hours Used"] or u["Bookings"] for u in usage):
            df = pd.DataFrame(usage).set_index("Equipment")
            st.bar_chart(df[["Hours Used"]] if df["Hours Used"].sum() > 0 else df[["Booked Hours"]])
        else:
            st.info(L("No usage data yet.", "ಇನ್ನೂ ಬಳಕೆಯ ಮಾಹಿತಿ ಇಲ್ಲ.", "अभी तक कोई उपयोग डेटा नहीं।"))
    with right:
        st.markdown("#### 📅 " + L("Today's schedule", "ಇಂದಿನ ವೇಳಾಪಟ್ಟಿ", "आज का कार्यक्रम"))
        if data["today"]:
            show_records(data["today"])
        else:
            st.info(L("No bookings today.", "ಇಂದು ಬುಕ್ಕಿಂಗ್ ಇಲ್ಲ.", "आज कोई बुकिंग नहीं।"))


def calendar_page():
    user = st.session_state.current_user
    st.title("📆 " + tr("Calendar"))
    st.caption(L("Coloured slots show who has what booked. It refreshes automatically for every logged-in user.",
                 "ಬಣ್ಣದ ಸಮಯಗಳು ಬುಕ್ಕಿಂಗ್ ಸ್ಥಿತಿಯನ್ನು ತೋರಿಸುತ್ತವೆ. ಎಲ್ಲಾ ಬಳಕೆದಾರರಿಗೂ ತಾನಾಗಿ ನವೀಕರಣವಾಗುತ್ತದೆ.",
                 "रंगीन स्लॉट बुकिंग की स्थिति दिखाते हैं। यह सभी उपयोगकर्ताओं के लिए अपने आप अपडेट होता है।"))
    show_names = user["role"] in ("admin", "manager")
    tab_day, tab_month = st.tabs(["🗓️ " + L("Day view", "ದಿನದ ನೋಟ", "दिन का दृश्य"),
                                  "📅 " + L("Month view", "ತಿಂಗಳ ನೋಟ", "माह का दृश्य")])
    with tab_day:
        _calendar_day(show_names)
    with tab_month:
        _calendar_month(show_names)


@live(15)
def _calendar_day(show_names):
    day = st.date_input(tr("Booking Date"), value=date.today(), key="cal_day")
    machines = call_service(get_catalogue_machines) or []
    if not machines:
        st.info(tr("ಲಭ್ಯವಿರುವ equipment ಇಲ್ಲ."))
        return
    bookings = call_service(get_calendar_data, day, day, show_names) or []
    st.markdown(calendar_day_html(day, machines, bookings, show_names), unsafe_allow_html=True)
    st.markdown(calendar_legend(), unsafe_allow_html=True)
    st.caption(L("Hover over a coloured slot for booking details.", "ವಿವರಗಳಿಗಾಗಿ ಬಣ್ಣದ ಸಮಯದ ಮೇಲೆ ಮೌಸ್ ಇಡಿ.",
                 "विवरण के लिए रंगीन स्लॉट पर माउस ले जाएँ।"))


@live(30)
def _calendar_month(show_names):
    machines = call_service(get_catalogue_machines) or []
    if not machines:
        st.info(tr("ಲಭ್ಯವಿರುವ equipment ಇಲ್ಲ."))
        return
    today = date.today()
    c1, c2, c3 = st.columns([3, 1, 2])
    with c1:
        all_label = L("All equipment", "ಎಲ್ಲಾ ಯಂತ್ರಗಳು", "सभी उपकरण")
        pick = st.selectbox(tr("Equipment"), [0] + [m["id"] for m in machines], key="cal_m_machine",
                            format_func=lambda x: all_label if x == 0 else next(m["name"] + " · " + m["machine_code"] for m in machines if m["id"] == x))
    with c2:
        years = [today.year - 1, today.year, today.year + 1]
        year = st.selectbox(L("Year", "ವರ್ಷ", "वर्ष"), years, index=1, key="cal_m_year")
    with c3:
        month = st.selectbox(L("Month", "ತಿಂಗಳು", "माह"), list(range(1, 13)), index=today.month - 1,
                             format_func=lambda n: calendar.month_name[n], key="cal_m_month")

    weeks = calendar.Calendar(0).monthdatescalendar(year, month)
    first, last = weeks[0][0], weeks[-1][-1]
    bookings = call_service(get_calendar_data, first, last, show_names) or []
    chosen = None
    if pick:
        bookings = [b for b in bookings if b["machine_id"] == pick]
        chosen = next(m for m in machines if m["id"] == pick)
    blocked = bool(chosen and chosen["live_status"] in ("Under Service", "Unavailable"))
    if blocked:
        st.markdown(f'<div class="notice notice-bad">🔧 {esc(chosen["name"])}: {L("currently Under Service — it cannot be booked.", "ಪ್ರಸ್ತುತ ಸೇವೆಯಲ್ಲಿದೆ — ಬುಕ್ ಮಾಡಲು ಸಾಧ್ಯವಿಲ್ಲ.", "फिलहाल सर्विस में है — बुक नहीं किया जा सकता।")}</div>',
                    unsafe_allow_html=True)
    st.markdown(calendar_month_html(year, month, bookings, 1 if pick else len(machines), blocked), unsafe_allow_html=True)
    st.markdown('<div class="legend">'
                f'<span><i style="background:#eaf8ef"></i>{L("Free", "ಖಾಲಿ", "खाली")}</span>'
                f'<span><i style="background:#fff3d1"></i>{L("Partly booked", "ಭಾಗಶಃ ಬುಕ್", "आंशिक बुक")}</span>'
                f'<span><i style="background:#fbdcdc"></i>{L("Busy", "ಹೆಚ್ಚು ಬುಕ್", "व्यस्त")}</span>'
                f'<span><i style="background:#e9e9ee"></i>{L("Under Service", "ಸೇವೆಯಲ್ಲಿದೆ", "सर्विस में")}</span></div>',
                unsafe_allow_html=True)
    in_month = [b for b in bookings if b["date"].month == month and b["date"].year == year]
    if in_month:
        with st.expander(L("Bookings this month", "ಈ ತಿಂಗಳ ಬುಕ್ಕಿಂಗ್‌ಗಳು", "इस माह की बुकिंग") + f" ({len(in_month)})"):
            rows = []
            for b in in_month:
                row = {"Date": str(b["date"]), "Equipment": b["machine"], "Time": f"{b['start']:%H:%M}–{b['end']:%H:%M}",
                       "Status": b["status"]}
                if show_names:
                    row["Farmer"] = b["farmer"]
                rows.append(row)
            show_records(rows)



def manager_machine_status():
    st.title("🔧 " + tr("Equipment Service Status"))
    machines = call_service(get_catalogue_machines)
    if not machines:
        st.info("Equipment ಇಲ್ಲ.")
        return

    st.caption(L("Move equipment to Under Service so farmers see it and cannot book it. Every approved machine is listed, including those already under service.",
                 "ಯಂತ್ರವನ್ನು 'ಸೇವೆಯಲ್ಲಿದೆ' ಸ್ಥಿತಿಗೆ ಬದಲಿಸಿದರೆ ರೈತರಿಗೆ ಕಾಣುತ್ತದೆ ಮತ್ತು ಬುಕ್ ಮಾಡಲಾಗುವುದಿಲ್ಲ. ಈಗಾಗಲೇ ಸೇವೆಯಲ್ಲಿರುವವು ಸೇರಿ ಎಲ್ಲವೂ ಇಲ್ಲಿವೆ.",
                 "उपकरण को 'सर्विस में' करने पर किसान उसे देखेंगे और बुक नहीं कर पाएँगे। सर्विस में मौजूद उपकरण सहित सभी यहाँ सूचीबद्ध हैं।"))
    table = []
    for m in machines:
        left = SERVICE_INTERVAL_HOURS - m["hours_since_service"]
        table.append({
            "ID": m["machine_code"], "Equipment": m["name"], "Status": tr(m["live_status"]),
            "Total hours worked": round(m["service_hours"], 1),
            "Hours since last service": round(m["hours_since_service"], 1),
            "Hours until service": round(max(left, 0), 1) if left > 0 else "⚠️ DUE",
            "Upcoming bookings": m["upcoming_count"],
        })
    show_records(table)

    with st.container(border=True):
        by_id = {m["id"]: m for m in machines}
        mid = st.selectbox(tr("Equipment"), list(by_id), format_func=lambda x: f"{machine_text(by_id[x])}  ·  {tr(by_id[x]['live_status'])}")
        options = ["Available", "Under Service", "Unavailable"]
        current = by_id[mid]["status"]
        status = st.selectbox(tr("Status"), options, index=options.index(current) if current in options else 0,
                              format_func=tr, key=f"svc_status_{mid}")
        if status != "Available" and by_id[mid]["upcoming_count"]:
            st.warning(L(f"{by_id[mid]['upcoming_count']} upcoming booking(s) exist for this equipment. They stay in the system — review them in Booking Management.",
                         f"ಈ ಯಂತ್ರಕ್ಕೆ {by_id[mid]['upcoming_count']} ಮುಂಬರುವ ಬುಕ್ಕಿಂಗ್(ಗಳು) ಇವೆ. ಅವು ವ್ಯವಸ್ಥೆಯಲ್ಲೇ ಇರುತ್ತವೆ — ಬುಕ್ಕಿಂಗ್ ನಿರ್ವಹಣೆಯಲ್ಲಿ ಪರಿಶೀಲಿಸಿ.",
                         f"इस उपकरण की {by_id[mid]['upcoming_count']} आगामी बुकिंग हैं। वे सिस्टम में रहेंगी — बुकिंग प्रबंधन में देखें।"))

        if st.button("Save Status", type="primary"):
            result = call_service(set_machine_service_status, mid, status)
            if result is not None:
                _cached_service_overview.clear()
                flash("success", tr("Equipment status updated."))
                st.rerun()

    with st.container(border=True):
        st.markdown("##### 🛠️ " + L("Service completed?", "ಸೇವೆ ಮುಗಿಯಿತೇ?", "सर्विस पूरी हुई?"))
        st.caption(L("This restarts the 100-hour counter and sets the equipment back to Available.",
                     "ಇದು 100 ಗಂಟೆಗಳ ಎಣಿಕೆಯನ್ನು ಮತ್ತೆ ಆರಂಭಿಸಿ ಯಂತ್ರವನ್ನು 'ಲಭ್ಯ' ಮಾಡುತ್ತದೆ.",
                     "यह 100-घंटे की गिनती फिर से शुरू करता है और उपकरण को 'उपलब्ध' कर देता है।"))
        note = st.text_input(L("Service note (optional)", "ಸೇವಾ ಟಿಪ್ಪಣಿ (ಐಚ್ಛಿಕ)", "सर्विस नोट (वैकल्पिक)"), key="svc_note")
        if st.button("✅ " + L("Mark as serviced", "ಸೇವೆ ಮುಗಿದಿದೆ ಎಂದು ದಾಖಲಿಸಿ", "सर्विस पूरी दर्ज करें"), key="svc_done"):
            result = call_service(mark_machine_serviced, mid, note, st.session_state.current_user["id"])
            if result is not None:
                _cached_service_overview.clear()
                flash("success", L("Service recorded. Counter restarted and equipment is Available.",
                                   "ಸೇವೆ ದಾಖಲಾಗಿದೆ. ಎಣಿಕೆ ಮರು ಆರಂಭವಾಗಿದೆ; ಯಂತ್ರ ಲಭ್ಯವಾಗಿದೆ.",
                                   "सर्विस दर्ज हुई। गिनती फिर शुरू हुई और उपकरण उपलब्ध है।"))
                st.rerun()


def manager_bookings():
    st.title("📋 " + tr("Booking Management"))
    bookings = call_service(get_all_bookings)
    if bookings is None:
        return
    invoices = {i["booking_id"]: i for i in (call_service(get_all_invoices) or [])}

    f1, f2 = st.columns([2, 2])
    with f1:
        flt = st.selectbox(tr("Status"), ["All", "Confirmed", "In Progress", "Completed", "Cancelled"],
                           format_func=lambda x: L("All", "ಎಲ್ಲವೂ", "सभी") if x == "All" else tr(x), key="bm_filter")
    with f2:
        who = st.text_input("🔍 " + L("Search farmer / equipment", "ರೈತ / ಯಂತ್ರ ಹುಡುಕಿ", "किसान / उपकरण खोजें"), key="bm_search")
    shown = [b for b in bookings
             if (flt == "All" or val(b, "status") == flt)
             and (not who.strip() or who.strip().lower() in
                  f"{val(val(b, 'farmer'), 'full_name', '')} {val(val(b, 'machine'), 'name', '')}".lower())]

    rows = []
    for b in shown:
        inv = invoices.get(val(b, "id"))
        rows.append({
            "Booking ID": val(b, "id"),
            "Equipment": val(val(b, "machine"), "name", "Equipment"),
            "Farmer": val(val(b, "farmer"), "full_name", ""),
            "Date": str(val(b, "booking_date", "")),
            "Start": str(val(b, "start_time", "")),
            "Hours": val(b, "booked_hours", ""),
            "Status": val(b, "status", ""),
            "Bill": inv["invoice_no"] if inv and inv["has_bill"] else "—",
            "Payment": inv["payment_state"] if inv else "—",
        })
    show_records(rows)
    with st.expander("📤 " + L("Export bookings", "ಬುಕ್ಕಿಂಗ್ ಎಕ್ಸ್‌ಪೋರ್ಟ್", "बुकिंग निर्यात")):
        bulk_export(invoices_dataframe([invoices[r["Booking ID"]] for r in rows if r["Booking ID"] in invoices]),
                    f"bookings_{date.today():%Y%m%d}", "bm_all")

    if not shown:
        return

    st.divider()
    with st.container(border=True):
        by_id = {val(b, "id"): b for b in shown}
        bid = st.selectbox(
            "Choose Booking",
            list(by_id),
            format_func=lambda x: booking_text(by_id[x]),
            key="bm_choose",
        )
        status = st.selectbox(
            "Update Status",
            ["Confirmed", "In Progress", "Cancelled"],
        )

        if st.button("Update Status", type="primary"):
            result = call_service(update_booking_status, bid, status)
            if result is not None:
                if status == "Cancelled":
                    send_booking_cancellation(bid)   # tell the farmer; never blocks the update
                flash("success", tr("Status updated."))
                st.rerun()

    with st.container(border=True):
        staff_bill_panel(bid, f"bm_{bid}")


def manager_billing():
    st.title("🧾 " + tr("Billing"))
    tab_gen, tab_bills = st.tabs(["➕ " + L("Generate bill", "ಬಿಲ್ ರಚಿಸಿ", "बिल बनाएं"),
                                  "🧾 " + L("Bills and Dues", "ಬಿಲ್ ಮತ್ತು ಬಾಕಿ", "बिल और बकाया")])

    with tab_gen:
        billable = call_service(get_billable_bookings)
        if billable is None:
            return
        if not billable:
            st.info(L("No bookings are waiting for a bill. A booking appears here once its work date has arrived "
                      "(and it is not cancelled).",
                      "ಬಿಲ್‌ಗಾಗಿ ಕಾಯುತ್ತಿರುವ ಬುಕ್ಕಿಂಗ್ ಇಲ್ಲ. ಕೆಲಸದ ದಿನಾಂಕ ಬಂದ ನಂತರ (ರದ್ದಾಗದಿದ್ದರೆ) ಬುಕ್ಕಿಂಗ್ ಇಲ್ಲಿ ಕಾಣುತ್ತದೆ.",
                      "बिल के लिए कोई बुकिंग प्रतीक्षा में नहीं है। काम की तारीख आने पर (रद्द न हो तो) बुकिंग यहाँ दिखेगी।"))
        else:
            st.caption(L(f"{len(billable)} booking(s) can be billed now. Pick one, check the hours actually worked, and generate the bill.",
                         f"{len(billable)} ಬುಕ್ಕಿಂಗ್(ಗಳಿಗೆ) ಈಗ ಬಿಲ್ ಮಾಡಬಹುದು. ಒಂದನ್ನು ಆರಿಸಿ, ನಿಜವಾದ ಗಂಟೆ ಪರಿಶೀಲಿಸಿ, ಬಿಲ್ ರಚಿಸಿ.",
                         f"{len(billable)} बुकिंग का बिल अभी बन सकता है। एक चुनें, वास्तविक घंटे जाँचें और बिल बनाएं।"))
            farmers = sorted({i["farmer_name"] for i in billable})
            pick_farmer = st.selectbox(L("Farmer", "ರೈತ", "किसान"), ["All"] + farmers,
                                       format_func=lambda x: L("All farmers", "ಎಲ್ಲಾ ರೈತರು", "सभी किसान") if x == "All" else x,
                                       key="bill_farmer")
            options = [i for i in billable if pick_farmer == "All" or i["farmer_name"] == pick_farmer]
            by_id = {i["booking_id"]: i for i in options}
            with st.container(border=True):
                bid = st.selectbox(
                    L("Booking to bill", "ಬಿಲ್ ಮಾಡಬೇಕಾದ ಬುಕ್ಕಿಂಗ್", "बिल के लिए बुकिंग"), list(by_id),
                    format_func=lambda x: (f"#{x} | {by_id[x]['machine_name']} | {by_id[x]['farmer_name']} | "
                                           f"{by_id[x]['date']} | {by_id[x]['booked_hours']} h | {by_id[x]['status']}"),
                    key="bill_pick")
                staff_bill_panel(bid, f"bg_{bid}")

    with tab_bills:
        report = call_service(get_billing_report)
        if report is None:
            return
        if not report:
            st.info(L("No bills have been generated yet. Use the 'Generate bill' tab.",
                      "ಇನ್ನೂ ಯಾವುದೇ ಬಿಲ್ ರಚಿಸಲಾಗಿಲ್ಲ. 'ಬಿಲ್ ರಚಿಸಿ' ಟ್ಯಾಬ್ ಬಳಸಿ.",
                      "अभी कोई बिल नहीं बना। 'बिल बनाएं' टैब का उपयोग करें।"))
            return
        total, paid_t = sum(r["amount"] for r in report), sum(r["paid"] for r in report)
        c1, c2, c3 = st.columns(3)
        c1.metric(tr("Total Billed"), money(total))
        c2.metric(tr("Total Collected"), money(paid_t))
        c3.metric(tr("Outstanding Due"), money(total - paid_t))

        state_of = lambda r: "Paid" if r["due"] <= 0 else ("Partial" if r["paid"] > 0 else "Unpaid")
        sel = st.selectbox(tr("Status"), ["All", "Unpaid", "Partial", "Paid"],
                           format_func=lambda x: L("All", "ಎಲ್ಲವೂ", "सभी") if x == "All" else tr(x), key="bills_state")
        rows = [r for r in report if sel == "All" or state_of(r) == sel]
        table = [{"Bill ID": r["bill_id"], "Booking ID": r["booking_id"], "Farmer": r["farmer"],
                  "Equipment": r["equipment"], "Hours": r["hours_used"], "Rate": r["hourly_rate"],
                  "Amount": r["amount"], "Paid": r["paid"], "Due": r["due"], "Status": state_of(r),
                  "Date": f"{r['created_at']:%Y-%m-%d}" if r["created_at"] else ""} for r in rows]
        show_records(table)
        bulk_export(pd.DataFrame(table), f"bills_{date.today():%Y%m%d}", "bills_all")

        if rows:
            st.divider()
            with st.container(border=True):
                by_bill = {r["bill_id"]: r for r in rows}
                bill_id = st.selectbox(
                    L("Open a bill", "ಬಿಲ್ ತೆರೆಯಿರಿ", "बिल खोलें"), list(by_bill),
                    format_func=lambda x: (f"Bill #{x} | {by_bill[x]['farmer']} | {by_bill[x]['equipment']} | "
                                           f"{money(by_bill[x]['amount'])} | Due {money(by_bill[x]['due'])}"),
                    key="bills_open")
                staff_bill_panel(by_bill[bill_id]["booking_id"], f"bb_{bill_id}")


def manager_payments():
    st.title("💳 " + tr("Payments"))

    report = call_service(get_billing_report)
    if report is None:
        return
    if not report:
        st.info(L("There are no bills yet, so there is nothing to collect. Generate a bill first.",
                  "ಇನ್ನೂ ಬಿಲ್‌ಗಳಿಲ್ಲ, ಆದ್ದರಿಂದ ಸಂಗ್ರಹಿಸಲು ಏನೂ ಇಲ್ಲ. ಮೊದಲು ಬಿಲ್ ರಚಿಸಿ.",
                  "अभी कोई बिल नहीं है, इसलिए वसूली के लिए कुछ नहीं। पहले बिल बनाएं।"))
        if st.button("🧾 " + L("Go to Billing", "ಬಿಲ್ಲಿಂಗ್‌ಗೆ ಹೋಗಿ", "बिलिंग पर जाएँ"), type="primary"):
            st.session_state._nav_request = "Billing"
            st.rerun()
        return

    tab_collect, tab_hist = st.tabs(["💰 " + L("Collect payment", "ಪಾವತಿ ಸಂಗ್ರಹ", "भुगतान लें"),
                                     "📜 " + L("Payment history", "ಪಾವತಿ ಇತಿಹಾಸ", "भुगतान इतिहास")])

    with tab_collect:
        due_items = [r for r in report if r["due"] > 0]
        total_due = sum(r["due"] for r in due_items)
        c1, c2 = st.columns(2)
        c1.metric(L("Bills with dues", "ಬಾಕಿ ಇರುವ ಬಿಲ್‌ಗಳು", "बकाया वाले बिल"), len(due_items))
        c2.metric(tr("Outstanding Due"), money(total_due))
        if not due_items:
            st.success(tr("Outstanding payments ಇಲ್ಲ."))
        else:
            by_bill = {r["bill_id"]: r for r in due_items}
            with st.container(border=True):
                bid = st.selectbox(
                    "Bill", list(by_bill),
                    format_func=lambda x: (f"Bill #{x} | {by_bill[x]['farmer']} | {by_bill[x]['equipment']} | "
                                           f"Due {money(by_bill[x]['due'])}"),
                    key="pay_bill")
                item = by_bill[bid]
                st.caption(f"{item['farmer']} · {item['equipment']} · {money(item['amount'])} "
                           f"({L('paid', 'ಪಾವತಿ', 'भुगतान')} {money(item['paid'])})")
                payment_form(bid, item["due"], f"pay_{bid}", f"Bill INV-{bid:06d}")

    with tab_hist:
        payments = call_service(get_all_payments) or []
        if not payments:
            st.info(L("No payments recorded yet.", "ಇನ್ನೂ ಪಾವತಿಗಳು ದಾಖಲಾಗಿಲ್ಲ.", "अभी कोई भुगतान दर्ज नहीं हुआ।"))
        else:
            df = pd.DataFrame([{"Payment ID": p["payment_id"], "Date": p["date"], "Bill ID": p["bill_id"],
                                "Booking ID": p["booking_id"], "Farmer": p["farmer"], "Equipment": p["equipment"],
                                "Amount": p["amount"], "Method": p["method"], "Reference": p["reference"]}
                               for p in payments])
            k1, k2 = st.columns(2)
            k1.metric(tr("Total Collected"), money(df["Amount"].sum()))
            k2.metric(L("Payments", "ಪಾವತಿಗಳು", "भुगतान"), len(df))
            by_method = df.groupby("Method")["Amount"].sum()
            st.bar_chart(by_method)
            st.dataframe(df, use_container_width=True, hide_index=True)
            bulk_export(df, f"payments_{date.today():%Y%m%d}", "pay_hist")


def _billing_summary_report():
    report = call_service(get_billing_report)
    if report is None:
        return
    if not report:
        st.info(tr("Billing records ಇಲ್ಲ."))
        return

    rows = []
    for item in report:
        amount = float(val(item, "amount", 0) or 0)
        paid = float(val(item, "paid", 0) or 0)
        due = float(val(item, "due", val(item, "due_amount", amount - paid)) or 0)
        rows.append({
            "Bill ID": val(item, "bill_id", val(item, "id")),
            "Booking ID": val(item, "booking_id"),
            "Amount": amount,
            "Paid": paid,
            "Due": due,
            "Date": val(item, "created_at", val(item, "date")),
        })

    df = pd.DataFrame(rows)
    c1, c2, c3 = st.columns(3)
    c1.metric(tr("Total Billed"), money(df["Amount"].sum()))
    c2.metric(tr("Total Collected"), money(df["Paid"].sum()))
    c3.metric(tr("Outstanding Due"), money(df["Due"].sum()))

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    dated = df.dropna(subset=["Date"]).copy()

    if not dated.empty:
        dated["Month"] = dated["Date"].dt.to_period("M").astype(str)
        monthly = dated.groupby("Month")[["Amount", "Paid", "Due"]].sum()
        st.subheader(tr("Monthly Summary"))
        st.bar_chart(monthly)

    st.dataframe(df, use_container_width=True, hide_index=True)
    st.download_button(
        tr("Download CSV"),
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="farm_equipment_report.csv",
        mime="text/csv",
    )


def _monthly_report_tab():
    today = date.today()
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        year = st.selectbox(L("Year", "ವರ್ಷ", "वर्ष"), [today.year - i for i in range(0, 5)], key="rep_year")
    with c2:
        month = st.selectbox(L("Month", "ತಿಂಗಳು", "माह"), list(range(1, 13)), index=today.month - 1,
                             format_func=lambda n: calendar.month_name[n], key="rep_month")
    with c3:
        st.write("")
        all_dues = st.checkbox(L("Include dues from all months", "ಎಲ್ಲಾ ತಿಂಗಳ ಬಾಕಿ ಸೇರಿಸಿ", "सभी महीनों का बकाया शामिल करें"), key="rep_all_dues")

    report = call_service(get_monthly_report, year, month, all_dues)
    if report is None:
        return
    machines_df = pd.DataFrame(report["machines"])
    dues_df = pd.DataFrame(report["dues"])
    k = st.columns(4)
    k[0].metric(L("Hours used", "ಬಳಸಿದ ಗಂಟೆ", "उपयोग घंटे"), round(machines_df["Hours Used"].sum(), 2) if not machines_df.empty else 0)
    k[1].metric(tr("Total Billed"), money(machines_df["Billed (₹)"].sum() if not machines_df.empty else 0))
    k[2].metric("💰 " + L("Money collected", "ಸಂಗ್ರಹಿಸಿದ ಹಣ", "वसूली गई राशि"), money(machines_df["Collected (₹)"].sum() if not machines_df.empty else 0))
    k[3].metric(tr("Outstanding Due"), money(dues_df["Pending (₹)"].sum() if not dues_df.empty else 0))

    st.subheader("🚜 " + L("Hours used per machine", "ಪ್ರತಿ ಯಂತ್ರದ ಬಳಕೆ ಗಂಟೆ", "प्रति उपकरण उपयोग घंटे"))
    if machines_df.empty:
        st.info(tr("ಲಭ್ಯವಿರುವ equipment ಇಲ್ಲ."))
    else:
        if machines_df["Hours Used"].sum() > 0:
            st.bar_chart(machines_df.set_index("Equipment")[["Hours Used"]])
        st.dataframe(machines_df, use_container_width=True, hide_index=True)
        st.download_button(tr("Download CSV"), machines_df.to_csv(index=False).encode("utf-8"),
                           file_name=f"machine_report_{year}_{month:02d}.csv", mime="text/csv", key="dl_machine_rep")

    st.subheader("⏳ " + L("Farmers with pending dues", "ಬಾಕಿ ಇರುವ ರೈತರು", "बकाया वाले किसान"))
    if dues_df.empty:
        st.success(tr("Outstanding payments ಇಲ್ಲ."))
    else:
        st.dataframe(dues_df, use_container_width=True, hide_index=True)
        st.download_button(tr("Download CSV"), dues_df.to_csv(index=False).encode("utf-8"),
                           file_name=f"pending_dues_{year}_{month:02d}.csv", mime="text/csv", key="dl_dues_rep")


def _most_used_tab():
    periods = ["All time", "This month", "Last 30 days"]
    labels = {"All time": L("All time", "ಎಲ್ಲಾ ಸಮಯ", "सभी समय"), "This month": L("This month", "ಈ ತಿಂಗಳು", "इस माह"),
              "Last 30 days": L("Last 30 days", "ಕಳೆದ 30 ದಿನ", "पिछले 30 दिन")}
    c1, c2 = st.columns(2)
    with c1:
        period = st.selectbox(L("Period", "ಅವಧಿ", "अवधि"), periods, format_func=labels.get, key="mu_period")
    with c2:
        metric = st.selectbox(L("Measure", "ಅಳತೆ", "माप"), ["Hours Used", "Bookings", "Booked Hours"], key="mu_metric")
    today = date.today()
    start, end = None, None
    if period == "This month":
        start = today.replace(day=1)
    elif period == "Last 30 days":
        start = today - timedelta(days=30)
    usage = call_service(get_machine_usage, start, end) or []
    if not usage or not any(u[metric] for u in usage):
        st.info(L("No usage data for this period yet.", "ಈ ಅವಧಿಗೆ ಇನ್ನೂ ಬಳಕೆಯ ಮಾಹಿತಿ ಇಲ್ಲ.", "इस अवधि का अभी कोई उपयोग डेटा नहीं।"))
        return
    df = pd.DataFrame(usage).sort_values(metric, ascending=False)
    top = df.head(3).reset_index(drop=True)
    cols = st.columns(len(top))
    for i, row in top.iterrows():
        cols[i].metric(["🥇", "🥈", "🥉"][i] + " " + row["Equipment"], row[metric])
    st.bar_chart(df.set_index("Equipment")[[metric]])
    st.dataframe(df, use_container_width=True, hide_index=True)


def manager_reports():
    st.title("📊 " + tr("Monthly Reports"))
    t1, t2, t3 = st.tabs([
        "📅 " + L("Monthly report", "ಮಾಸಿಕ ವರದಿ", "मासिक रिपोर्ट"),
        "🏆 " + L("Most used machines", "ಹೆಚ್ಚು ಬಳಸಿದ ಯಂತ್ರಗಳು", "सबसे ज्यादा उपयोग वाले उपकरण"),
        "🧾 " + L("Billing summary", "ಬಿಲ್ಲಿಂಗ್ ಸಾರಾಂಶ", "बिलिंग सारांश"),
    ])
    with t1:
        _monthly_report_tab()
    with t2:
        _most_used_tab()
    with t3:
        _billing_summary_report()


# =========================================================
# MAIN ROUTER
# =========================================================

FARMER_PAGES = [
    "Dashboard",
    "Equipment Catalogue",
    "Calendar",
    "Register Equipment",
    "Book Equipment",
    "My Bookings",
    "Weather & AI",
]


# Admin does everything the manager can, plus equipment approvals. The "manager" role keeps working as before.
_STAFF_COMMON = ["Calendar", "Booking Management", "Billing", "Payments", "Equipment Service Status", "Monthly Reports"]
ADMIN_PAGES = ["Overview", "Equipment Approvals"] + _STAFF_COMMON
MANAGER_PAGES = ["Overview"] + _STAFF_COMMON


def main():
    user = st.session_state.current_user

    if not user:
        st.session_state.app_language = "English"
        page = st.session_state.page

        if page == "register":
            registration_page()
        elif page == "verify_otp":
            otp_page()
        elif page == "forgot_password":
            forgot_password_page()
        else:
            login_page()
        return

    role = user["role"]

    # Pages (e.g. catalogue "Book" button) can request a page switch; apply it before the radio is created.
    _req = st.session_state.pop("_nav_request", None)
    if _req:
        if role in ("admin", "manager"):
            if _req in (ADMIN_PAGES if role == "admin" else MANAGER_PAGES):
                st.session_state["staff_nav"] = _req
        else:
            st.session_state["farmer_nav"] = _req

    with st.sidebar:
        st.markdown("## 🌱 Krishi Equipment")
        with st.container(border=True):
            st.markdown(f"**{user['full_name']}**")
            st.caption(user["email"])
            st.markdown(badge(role.title()), unsafe_allow_html=True)
        current_language = user.get("preferred_language", st.session_state.get("app_language", "English"))
        selected_language = st.selectbox(
            tr("Choose language"),
            ["English", "Kannada", "Hindi"],
            index=["English", "Kannada", "Hindi"].index(current_language) if current_language in ["English", "Kannada", "Hindi"] else 0,
            format_func=lambda x: LANGUAGES[x],
            key="sidebar_language_selector",
        )
        if selected_language != st.session_state.get("app_language", "English"):
            with SessionLocal() as db:
                db_user = db.query(User).filter(User.id == user["id"]).first()
                if db_user:
                    db_user.preferred_language = selected_language
                    db.commit()
            user["preferred_language"] = selected_language
            st.session_state.current_user = user
            st.session_state.app_language = selected_language
            st.rerun()
        st.divider()

        if role == "admin":
            page = st.radio(tr("Admin Menu"), ADMIN_PAGES, format_func=tr, key="staff_nav")
        elif role == "manager":
            page = st.radio(tr("Manager Menu"), MANAGER_PAGES, format_func=tr, key="staff_nav")
        else:
            # key="farmer_nav" lets the dashboard quick-action buttons switch pages.
            page = st.radio(
                tr("Farmer Menu"),
                FARMER_PAGES,
                format_func=tr,
                key="farmer_nav",
            )

        st.divider()
        # Refresh the current Streamlit view without clearing the logged-in session.
        # st.rerun() re-executes the app while preserving st.session_state.
        if st.button("🔄 Refresh Page", use_container_width=True, key="refresh_current_page"):
            st.rerun()

        if st.button(tr("Logout"), use_container_width=True):
            logout()

    show_flash()

    if role in ("admin", "manager"):
        staff_service_banner()
        if page == "Overview":
            admin_overview()
        elif page == "Equipment Approvals" and role == "admin":
            admin_panel()
        elif page == "Calendar":
            calendar_page()
        elif page == "Booking Management":
            manager_bookings()
        elif page == "Billing":
            manager_billing()
        elif page == "Payments":
            manager_payments()
        elif page == "Equipment Service Status":
            manager_machine_status()
        elif page == "Monthly Reports":
            manager_reports()

    else:
        if page == "Dashboard":
            farmer_dashboard(user)
        elif page == "Equipment Catalogue":
            farmer_catalogue()
        elif page == "Calendar":
            calendar_page()
        elif page == "Register Equipment":
            farmer_register_machine()
        elif page == "Book Equipment":
            farmer_booking()
        elif page == "My Bookings":
            farmer_my_bookings()
        elif page == "Weather & AI":
            farmer_ai_weather()


if __name__ == "__main__":
    main()
