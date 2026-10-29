from datetime import date, datetime, timedelta
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload
from database import SessionLocal, Booking, Bill, Payment, Machine, User, ServiceLog

class ServiceError(ValueError):
    """Safe, user-readable business-rule error."""

ACTIVE_BOOKING_STATUSES = ("Confirmed", "Approved", "In Progress")


def _machine_code(machine):
    if not machine.machine_code:
        machine.machine_code = f"KE-{machine.id:06d}"
    return machine.machine_code


def list_approved_machines():
    """Return approved, operational machines; booked slots are validated at booking time."""
    with SessionLocal() as db:
        machines = (db.query(Machine)
                    .filter(Machine.approval_status == "Approved", Machine.status == "Available")
                    .order_by(Machine.name, Machine.id).all())
        now = datetime.now()
        visible = []
        for machine in machines:
            _machine_code(machine)
            # Hide a machine from the catalogue while someone is using it right now.
            # Future reservations remain visible for non-overlapping time-slot bookings.
            active = (db.query(Booking).filter(
                Booking.machine_id == machine.id,
                Booking.booking_date == now.date(),
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            ).all())
            occupied_now = False
            for booking in active:
                begin = datetime.combine(booking.booking_date, booking.start_time)
                finish = begin + timedelta(hours=int(booking.booked_hours))
                if begin <= now < finish:
                    occupied_now = True
                    break
            if not occupied_now:
                visible.append(machine)
        db.commit()
        return visible


def register_equipment(owner_id, name, hourly_rate, description="", location="", contact_phone=""):
    if not name or len(name.strip()) < 2:
        raise ServiceError("ಯಂತ್ರದ ಹೆಸರು ಕನಿಷ್ಠ 2 ಅಕ್ಷರಗಳಿರಬೇಕು.")
    if float(hourly_rate) <= 0:
        raise ServiceError("Hourly rate ಶೂನ್ಯಕ್ಕಿಂತ ಹೆಚ್ಚಿರಬೇಕು.")
    with SessionLocal() as db:
        owner = db.get(User, int(owner_id))
        if owner is None:
            raise ServiceError("User account ಕಂಡುಬಂದಿಲ್ಲ. ಮತ್ತೆ login ಮಾಡಿ.")
        machine = Machine(name=name.strip()[:60], hourly_rate=float(hourly_rate), description=(description or "").strip(),
                          location=(location or "").strip()[:180], contact_phone=(contact_phone or "").strip()[:10],
                          owner_id=owner.id, status="Available", approval_status="Pending")
        db.add(machine)
        db.flush()
        machine.machine_code = f"KE-{machine.id:06d}"
        db.commit()
        db.refresh(machine)
        return machine


def get_farmer_equipment(owner_id):
    with SessionLocal() as db:
        return db.query(Machine).filter(Machine.owner_id == int(owner_id)).order_by(Machine.id.desc()).all()


def get_pending_equipment():
    with SessionLocal() as db:
        return db.query(Machine).options(joinedload(Machine.owner)).filter(Machine.approval_status == "Pending").order_by(Machine.id.asc()).all()


def review_equipment(machine_id, decision):
    decision = str(decision).strip().title()
    if decision not in ("Approved", "Rejected"):
        raise ServiceError("Invalid approval decision.")
    with SessionLocal() as db:
        machine = db.get(Machine, int(machine_id))
        if machine is None:
            raise ServiceError("Equipment ಕಂಡುಬಂದಿಲ್ಲ.")
        machine.approval_status = decision
        db.commit()
        db.refresh(machine)
        return machine


def booking_conflict(db, machine_id, booking_date, start_time, hours, exclude_id=None):
    start_dt = datetime.combine(booking_date, start_time)
    end_dt = start_dt + timedelta(hours=int(hours))
    query = db.query(Booking).filter(Booking.machine_id == int(machine_id),
        Booking.booking_date == booking_date, Booking.status.in_(ACTIVE_BOOKING_STATUSES))
    if exclude_id is not None:
        query = query.filter(Booking.id != int(exclude_id))
    for existing in query.all():
        old_start = datetime.combine(existing.booking_date, existing.start_time)
        old_end = old_start + timedelta(hours=int(existing.booked_hours))
        if start_dt < old_end and old_start < end_dt:
            return existing
    return None


def book_machine(farmer_id, machine_id, booking_date, start_time, hours, notes=""):
    """Atomically lock the machine, re-check overlap, and commit exactly one booking.

    MySQL/InnoDB's SELECT ... FOR UPDATE serializes competing booking requests for the
    same machine, so the first committed request wins and later overlapping requests fail.
    """
    hours = int(hours)
    if booking_date < date.today():
        raise ServiceError("ಹಿಂದಿನ ದಿನಾಂಕಕ್ಕೆ booking ಮಾಡಲು ಸಾಧ್ಯವಿಲ್ಲ.")
    if not 1 <= hours <= 10:
        raise ServiceError("Booking 1ರಿಂದ 10 ಗಂಟೆಗಳವರೆಗೆ ಇರಬೇಕು.")
    end_dt = datetime.combine(booking_date, start_time) + timedelta(hours=hours)
    if end_dt.date() != booking_date:
        raise ServiceError("Booking ಒಂದೇ ದಿನದೊಳಗೆ ಮುಗಿಯಬೇಕು; ಮಧ್ಯರಾತ್ರಿ ದಾಟುವ booking ಬೆಂಬಲಿತವಲ್ಲ.")
    with SessionLocal() as db:
        try:
            # MySQL row lock prevents two concurrent sessions booking the same machine slot.
            machine = db.query(Machine).filter(Machine.id == int(machine_id)).with_for_update().first()
            if machine is None:
                raise ServiceError("Machine ಕಂಡುಬಂದಿಲ್ಲ.")
            if db.get(User, int(farmer_id)) is None:
                raise ServiceError("User account ಕಂಡುಬಂದಿಲ್ಲ. ಮತ್ತೆ login ಮಾಡಿ.")
            if machine.approval_status != "Approved":
                raise ServiceError("ಈ equipment ಇನ್ನೂ admin approval ಪಡೆದಿಲ್ಲ.")
            if machine.status != "Available":
                raise ServiceError("ಈ ಯಂತ್ರ Under Service/Unavailable ಇದೆ; booking ಸಾಧ್ಯವಿಲ್ಲ.")
            conflict = booking_conflict(db, machine.id, booking_date, start_time, hours)
            if conflict:
                conflict_end = datetime.combine(conflict.booking_date, conflict.start_time) + timedelta(hours=conflict.booked_hours)
                raise ServiceError(f"ಈ ಯಂತ್ರ ಈಗಾಗಲೇ ಬುಕ್ ಆಗಿದೆ: Booking #{conflict.id}, {conflict.start_time.strftime('%H:%M')}–{conflict_end.strftime('%H:%M')}. ಬೇರೆ ಸಮಯ ಆಯ್ಕೆಮಾಡಿ.")
            booking = Booking(machine_id=machine.id, farmer_id=int(farmer_id), booking_date=booking_date,
                              start_time=start_time, booked_hours=hours, status="Confirmed", notes=(notes or "").strip())
            db.add(booking)
            db.commit()
            db.refresh(booking)
            return booking
        except Exception:
            db.rollback()
            raise


def get_booked_slots(machine_id, booking_date):
    with SessionLocal() as db:
        rows = db.query(Booking).filter(Booking.machine_id == int(machine_id), Booking.booking_date == booking_date,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES)).order_by(Booking.start_time).all()
        return [{"Booking ID": b.id, "Date": str(b.booking_date), "Start": str(b.start_time),
                 "End": str((datetime.combine(b.booking_date, b.start_time) + timedelta(hours=b.booked_hours)).time()),
                 "Hours": b.booked_hours, "Status": b.status} for b in rows]


def get_farmer_bookings(farmer_id):
    with SessionLocal() as db:
        return (db.query(Booking).options(joinedload(Booking.machine), joinedload(Booking.bill))
                .filter(Booking.farmer_id == int(farmer_id)).order_by(Booking.created_at.desc()).all())


def get_all_bookings():
    with SessionLocal() as db:
        return (db.query(Booking).options(joinedload(Booking.machine), joinedload(Booking.farmer), joinedload(Booking.bill))
                .order_by(Booking.created_at.desc()).all())


def update_booking_status(booking_id, status):
    status = str(status).strip().title()
    allowed = {"Confirmed", "Approved", "In Progress", "Completed", "Cancelled"}
    if status not in allowed:
        raise ServiceError("Invalid booking status.")
    with SessionLocal() as db:
        booking = db.get(Booking, int(booking_id))
        if booking is None:
            raise ServiceError("Booking ಕಂಡುಬಂದಿಲ್ಲ.")
        if booking.status == "Completed" and status != "Completed":
            raise ServiceError("Completed booking ಸ್ಥಿತಿಯನ್ನು ಹಿಂದಕ್ಕೆ ಬದಲಾಯಿಸಲಾಗುವುದಿಲ್ಲ.")
        if status == "Cancelled" and db.query(Bill).filter_by(booking_id=booking.id).first():
            raise ServiceError("This booking can no longer be cancelled.")
        if booking.status == "Cancelled" and status in ACTIVE_BOOKING_STATUSES:
            clash = booking_conflict(db, booking.machine_id, booking.booking_date, booking.start_time,
                                     booking.booked_hours, exclude_id=booking.id)
            if clash:
                end = datetime.combine(clash.booking_date, clash.start_time) + timedelta(hours=clash.booked_hours)
                raise ServiceError(f"ಈ ಯಂತ್ರ ಈಗಾಗಲೇ ಬುಕ್ ಆಗಿದೆ: Booking #{clash.id}, {clash.start_time.strftime('%H:%M')}–{end.strftime('%H:%M')}. ಬೇರೆ ಸಮಯ ಆಯ್ಕೆಮಾಡಿ.")
        booking.status = status
        db.commit()
        db.refresh(booking)
        return booking


def create_bill(booking_id, hours_used):
    with SessionLocal() as db:
        booking = db.query(Booking).options(joinedload(Booking.machine)).filter(Booking.id == int(booking_id)).with_for_update().first()
        if not booking:
            raise ServiceError("Booking ಕಂಡುಬಂದಿಲ್ಲ.")
        if booking.status == "Cancelled":
            raise ServiceError("Cancelled bookingಗೆ bill ಮಾಡಲಾಗುವುದಿಲ್ಲ.")
        if booking.booking_date > date.today():
            raise ServiceError("ಕೆಲಸ ನಡೆದ ದಿನಾಂಕದ ನಂತರ ಮಾತ್ರ bill ಸಿದ್ಧಪಡಿಸಬಹುದು.")
        if float(hours_used) <= 0 or float(hours_used) > 24:
            raise ServiceError("Actual hours 0ಕ್ಕಿಂತ ಹೆಚ್ಚು ಮತ್ತು 24ಕ್ಕಿಂತ ಕಡಿಮೆ ಇರಬೇಕು.")
        if db.query(Bill).filter_by(booking_id=booking.id).first():
            raise ServiceError("ಈ bookingಗೆ bill ಈಗಾಗಲೇ ಸಿದ್ಧವಾಗಿದೆ.")
        bill = Bill(booking_id=booking.id, hours_used=float(hours_used), hourly_rate=float(booking.machine.hourly_rate),
                    amount=round(float(hours_used) * float(booking.machine.hourly_rate), 2))
        booking.status = "Completed"
        booking.machine.service_hours = float(booking.machine.service_hours or 0) + float(hours_used)
        db.add(bill)
        db.commit()
        db.refresh(bill)
        return bill


def paid_amount(db, bill_id):
    return sum(float(p.amount) for p in db.query(Payment).filter_by(bill_id=int(bill_id)).all())


def record_payment(bill_id, amount, method, reference, recorded_by):
    with SessionLocal() as db:
        bill = db.get(Bill, int(bill_id))
        if not bill:
            raise ServiceError("Bill ಕಂಡುಬಂದಿಲ್ಲ.")
        amount = round(float(amount), 2)
        if amount <= 0:
            raise ServiceError("Payment amount ಶೂನ್ಯಕ್ಕಿಂತ ಹೆಚ್ಚಿರಬೇಕು.")
        due = round(float(bill.amount) - paid_amount(db, bill.id), 2)
        if amount > due + 0.0001:
            raise ServiceError(f"Payment pending amount ₹{due:,.2f} ಗಿಂತ ಹೆಚ್ಚಿರಬಾರದು.")
        payment = Payment(bill_id=bill.id, amount=amount, payment_date=date.today(), method=str(method),
                          reference=(reference or "").strip()[:100], recorded_by=int(recorded_by))
        db.add(payment)
        db.commit()
        db.refresh(payment)
        return payment


def get_billing_report():
    with SessionLocal() as db:
        bills = db.query(Bill).options(joinedload(Bill.booking).joinedload(Booking.machine),
                                      joinedload(Bill.booking).joinedload(Booking.farmer),
                                      joinedload(Bill.payments)).order_by(Bill.created_at.desc()).all()
        result = []
        for bill in bills:
            paid = sum(float(p.amount) for p in bill.payments)
            result.append({"bill_id": bill.id, "booking_id": bill.booking_id,
                "farmer": bill.booking.farmer.full_name if bill.booking and bill.booking.farmer else "",
                "equipment": bill.booking.machine.name if bill.booking and bill.booking.machine else "",
                "hours_used": bill.hours_used, "hourly_rate": bill.hourly_rate,
                "amount": bill.amount, "paid": round(paid, 2), "due": round(float(bill.amount)-paid, 2),
                "created_at": bill.created_at})
        return result


def set_machine_service_status(machine_id, status):
    allowed = {"Available", "Under Service", "Unavailable"}
    if status not in allowed:
        raise ServiceError("Invalid equipment status.")
    with SessionLocal() as db:
        machine = db.get(Machine, int(machine_id))
        if machine is None:
            raise ServiceError("Equipment ಕಂಡುಬಂದಿಲ್ಲ.")
        machine.status = status
        db.commit()
        db.refresh(machine)
        return machine



# =====================================================================
# NEW FEATURES (additive) — live catalogue, slot pre-check, calendar,
# service reminders, farmer bill/payment view, reports, charts.
# =====================================================================
SERVICE_INTERVAL_HOURS = 100   # a machine needs servicing after this many worked hours
SERVICE_WARNING_HOURS = 90     # early warning


def _window(booking):
    start = datetime.combine(booking.booking_date, booking.start_time)
    return start, start + timedelta(hours=int(booking.booked_hours))


def _hm(dt):
    return dt.strftime("%H:%M")


def _service_baseline(db, machine_id):
    row = (db.query(ServiceLog).filter(ServiceLog.machine_id == machine_id)
           .order_by(ServiceLog.id.desc()).first())
    return (float(row.hours_at_service or 0), row.serviced_at) if row else (0.0, None)


def _service_level(since):
    if since >= SERVICE_INTERVAL_HOURS:
        return "due"
    if since >= SERVICE_WARNING_HOURS:
        return "soon"
    return "ok"


def get_catalogue_machines():
    """Every approved machine (including Under Service ones) with its LIVE status.

    live_status: "Under Service" | "Unavailable" | "Booked Now" | "Available".
    Also returns today's booked slots, the next booking, and service-hour counters.
    """
    with SessionLocal() as db:
        now = datetime.now()
        machines = (db.query(Machine).filter(Machine.approval_status == "Approved")
                    .order_by(Machine.name, Machine.id).all())
        active = (db.query(Booking).filter(Booking.booking_date >= now.date(),
                                           Booking.status.in_(ACTIVE_BOOKING_STATUSES))
                  .order_by(Booking.booking_date, Booking.start_time).all())
        by_machine = {}
        for b in active:
            by_machine.setdefault(b.machine_id, []).append(b)
        result = []
        for m in machines:
            code = _machine_code(m)
            busy_until, next_slot, today_slots, upcoming = None, None, [], 0
            for b in by_machine.get(m.id, []):
                start, end = _window(b)
                if end <= now:
                    continue
                upcoming += 1
                if start <= now < end:
                    busy_until = end
                elif next_slot is None and start > now:
                    next_slot = f"{start.strftime('%d %b')} {_hm(start)}–{_hm(end)}"
                if b.booking_date == now.date():
                    today_slots.append(f"{_hm(start)}–{_hm(end)}")
            if m.status == "Under Service":
                live = "Under Service"
            elif m.status != "Available":
                live = "Unavailable"
            elif busy_until:
                live = "Booked Now"
            else:
                live = "Available"
            baseline, last_serviced = _service_baseline(db, m.id)
            since = round(float(m.service_hours or 0) - baseline, 2)
            result.append({
                "id": m.id, "machine_code": code, "name": m.name, "hourly_rate": m.hourly_rate,
                "description": m.description, "location": m.location, "contact_phone": m.contact_phone,
                "status": m.status, "live_status": live, "busy_until": busy_until,
                "next_slot": next_slot, "today_slots": today_slots, "upcoming_count": upcoming,
                "service_hours": float(m.service_hours or 0), "hours_since_service": since,
                "service_level": _service_level(since), "last_serviced": last_serviced,
            })
        db.commit()
        return result


def check_slot(machine_id, booking_date, start_time, hours):
    """Read-only pre-check that mirrors book_machine, so the UI can warn BEFORE the click."""
    hours = int(hours)
    if booking_date < date.today():
        return {"ok": False, "code": "past_date"}
    if not 1 <= hours <= 10:
        return {"ok": False, "code": "bad_hours"}
    if (datetime.combine(booking_date, start_time) + timedelta(hours=hours)).date() != booking_date:
        return {"ok": False, "code": "midnight"}
    with SessionLocal() as db:
        machine = db.get(Machine, int(machine_id))
        if machine is None:
            return {"ok": False, "code": "machine_missing"}
        if machine.approval_status != "Approved":
            return {"ok": False, "code": "not_approved"}
        if machine.status != "Available":
            return {"ok": False, "code": "unavailable", "status": machine.status}
        clash = booking_conflict(db, machine.id, booking_date, start_time, hours)
        if clash:
            s, e = _window(clash)
            return {"ok": False, "code": "conflict", "booking_id": clash.id, "start": _hm(s), "end": _hm(e)}
    return {"ok": True, "code": "ok"}


def get_calendar_data(start_date, end_date, include_names=False):
    """Bookings (not cancelled) between two dates for the calendar views."""
    with SessionLocal() as db:
        rows = (db.query(Booking).options(joinedload(Booking.machine), joinedload(Booking.farmer))
                .filter(Booking.booking_date >= start_date, Booking.booking_date <= end_date,
                        Booking.status != "Cancelled")
                .order_by(Booking.booking_date, Booking.start_time).all())
        out = []
        for b in rows:
            s, e = _window(b)
            out.append({"booking_id": b.id, "machine_id": b.machine_id,
                        "machine": b.machine.name if b.machine else "", "date": b.booking_date,
                        "start": s, "end": e, "hours": b.booked_hours, "status": b.status,
                        "farmer": (b.farmer.full_name if (include_names and b.farmer) else "")})
        return out


def get_service_overview():
    """Per-machine service counters used for the 100-hour reminder."""
    return [{k: m[k] for k in ("id", "machine_code", "name", "status", "live_status", "service_hours",
                               "hours_since_service", "service_level", "last_serviced", "upcoming_count")}
            for m in get_catalogue_machines()]


def mark_machine_serviced(machine_id, note="", user_id=None):
    """Log a service, restart the 100-hour counter, and put the machine back to Available."""
    with SessionLocal() as db:
        machine = db.query(Machine).filter(Machine.id == int(machine_id)).with_for_update().first()
        if machine is None:
            raise ServiceError("Equipment ಕಂಡುಬಂದಿಲ್ಲ.")
        db.add(ServiceLog(machine_id=machine.id, hours_at_service=float(machine.service_hours or 0),
                          note=(note or "").strip()[:255], serviced_by=int(user_id) if user_id else None))
        machine.status = "Available"
        db.commit()
        db.refresh(machine)
        return machine


def cancel_booking(booking_id, user_id, is_staff=False):
    """A farmer may cancel their own not-yet-started booking; staff may cancel any non-completed one."""
    with SessionLocal() as db:
        booking = db.query(Booking).filter(Booking.id == int(booking_id)).with_for_update().first()
        if booking is None:
            raise ServiceError("Booking ಕಂಡುಬಂದಿಲ್ಲ.")
        if not is_staff and booking.farmer_id != int(user_id):
            raise ServiceError("You can only cancel your own bookings.")
        if booking.status not in ("Confirmed", "Approved") and not (is_staff and booking.status == "In Progress"):
            raise ServiceError("This booking can no longer be cancelled.")
        if db.query(Bill).filter_by(booking_id=booking.id).first():
            raise ServiceError("This booking can no longer be cancelled.")
        booking.status = "Cancelled"
        db.commit()
        db.refresh(booking)
        return booking


def get_farmer_bill_map(farmer_id):
    """booking_id -> bill, paid, pending and payment history, for the farmer's own bookings."""
    with SessionLocal() as db:
        bills = (db.query(Bill).join(Booking, Bill.booking_id == Booking.id)
                 .options(joinedload(Bill.payments), joinedload(Bill.booking).joinedload(Booking.machine))
                 .filter(Booking.farmer_id == int(farmer_id)).all())
        out = {}
        for bill in bills:
            paid = round(sum(float(p.amount) for p in bill.payments), 2)
            out[bill.booking_id] = {
                "bill_id": bill.id, "hours_used": bill.hours_used, "hourly_rate": bill.hourly_rate,
                "amount": float(bill.amount), "paid": paid, "due": round(float(bill.amount) - paid, 2),
                "equipment": bill.booking.machine.name if bill.booking and bill.booking.machine else "",
                "payments": [{"date": str(p.payment_date), "amount": float(p.amount), "method": p.method,
                              "reference": p.reference} for p in sorted(bill.payments, key=lambda x: x.id)]}
        return out


def get_machine_usage(start_date=None, end_date=None):
    """Most-used machines: bookings, booked hours and ACTUAL hours used (from bills)."""
    with SessionLocal() as db:
        machines = db.query(Machine).filter(Machine.approval_status == "Approved").all()
        q = db.query(Booking).options(joinedload(Booking.bill)).filter(Booking.status != "Cancelled")
        if start_date:
            q = q.filter(Booking.booking_date >= start_date)
        if end_date:
            q = q.filter(Booking.booking_date <= end_date)
        stats = {m.id: {"Equipment": m.name, "Bookings": 0, "Booked Hours": 0, "Hours Used": 0.0} for m in machines}
        for b in q.all():
            s = stats.get(b.machine_id)
            if s is None:
                continue
            s["Bookings"] += 1
            s["Booked Hours"] += int(b.booked_hours)
            if b.bill:
                s["Hours Used"] += float(b.bill.hours_used)
        rows = list(stats.values())
        for r in rows:
            r["Hours Used"] = round(r["Hours Used"], 2)
        return sorted(rows, key=lambda r: (r["Hours Used"], r["Bookings"]), reverse=True)


def _as_date(value):
    """Normalise a date / datetime (MySQL or SQLite may return either) to a plain date."""
    return value.date() if isinstance(value, datetime) else value


def get_monthly_report(year, month, all_time_dues=False):
    """Monthly report: hours used per machine, money collected, and farmers with pending dues."""
    first = date(int(year), int(month), 1)
    last = (date(first.year + (first.month == 12), first.month % 12 + 1, 1) - timedelta(days=1))
    with SessionLocal() as db:
        machines = db.query(Machine).filter(Machine.approval_status == "Approved").order_by(Machine.name).all()
        bookings = (db.query(Booking)
                    .options(joinedload(Booking.bill).joinedload(Bill.payments), joinedload(Booking.farmer))
                    .filter(Booking.status != "Cancelled").all())
        rows = {m.id: {"Equipment": m.name, "Bookings": 0, "Booked Hours": 0, "Hours Used": 0.0,
                       "Billed (₹)": 0.0, "Collected (₹)": 0.0} for m in machines}
        dues = {}
        for b in bookings:
            in_month = first <= _as_date(b.booking_date) <= last
            row = rows.get(b.machine_id)
            if in_month and row is not None:
                row["Bookings"] += 1
                row["Booked Hours"] += int(b.booked_hours)
            if not b.bill:
                continue
            paid_total = sum(float(p.amount) for p in b.bill.payments)
            if in_month and row is not None:
                row["Hours Used"] += float(b.bill.hours_used)
                row["Billed (₹)"] += float(b.bill.amount)
            if row is not None:   # money collected is counted by the date the payment was received
                row["Collected (₹)"] += sum(float(p.amount) for p in b.bill.payments if first <= _as_date(p.payment_date) <= last)
            due = round(float(b.bill.amount) - paid_total, 2)
            if due > 0 and (all_time_dues or in_month):
                f = b.farmer
                d = dues.setdefault(b.farmer_id, {"Farmer": f.full_name if f else "", "Village": f.village if f else "",
                                                  "Phone": f.phone if f else "", "Bills": 0, "Billed (₹)": 0.0,
                                                  "Paid (₹)": 0.0, "Pending (₹)": 0.0})
                d["Bills"] += 1
                d["Billed (₹)"] += float(b.bill.amount)
                d["Paid (₹)"] += paid_total
                d["Pending (₹)"] += due
        machine_rows = []
        for r in rows.values():
            for k in ("Hours Used", "Billed (₹)", "Collected (₹)"):
                r[k] = round(r[k], 2)
            machine_rows.append(r)
        dues_rows = sorted(dues.values(), key=lambda r: r["Pending (₹)"], reverse=True)
        for r in dues_rows:
            for k in ("Billed (₹)", "Paid (₹)", "Pending (₹)"):
                r[k] = round(r[k], 2)
        return {"machines": machine_rows, "dues": dues_rows, "month_start": first, "month_end": last}


def get_admin_overview():
    """Headline numbers for the admin dashboard."""
    with SessionLocal() as db:
        today = date.today()
        month_start = today.replace(day=1)
        pending = db.query(Machine).filter(Machine.approval_status == "Pending").count()
        under_service = db.query(Machine).filter(Machine.approval_status == "Approved",
                                                 Machine.status == "Under Service").count()
        machines = db.query(Machine).filter(Machine.approval_status == "Approved").count()
        today_rows = (db.query(Booking).options(joinedload(Booking.machine), joinedload(Booking.farmer))
                      .filter(Booking.booking_date == today, Booking.status != "Cancelled")
                      .order_by(Booking.start_time).all())
        active = db.query(Booking).filter(Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                                          Booking.booking_date >= today).count()
        billed = float(db.query(func.coalesce(func.sum(Bill.amount), 0)).scalar() or 0)
        paid = float(db.query(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0)
        collected_month = float(db.query(func.coalesce(func.sum(Payment.amount), 0))
                                .filter(Payment.payment_date >= month_start).scalar() or 0)
        return {"pending_approvals": pending, "under_service": under_service, "machines": machines,
                "active_bookings": active, "outstanding": round(billed - paid, 2),
                "collected_month": round(collected_month, 2),
                "today": [{"Time": f"{_hm(_window(b)[0])}–{_hm(_window(b)[1])}",
                           "Equipment": b.machine.name if b.machine else "",
                           "Farmer": b.farmer.full_name if b.farmer else "", "Status": b.status}
                          for b in today_rows]}


# =====================================================================
# NEW (billing / payments / export) — additive
# =====================================================================
def _invoice_dict(b):
    """Flat, display-ready dict for one booking (+ its bill and payments, if any).
    Must be called while the booking's machine, farmer, bill and payments are loaded."""
    start, end = _window(b)
    bill = b.bill
    machine, farmer = b.machine, b.farmer
    payments = sorted(bill.payments, key=lambda p: p.id) if bill else []
    paid = round(sum(float(p.amount) for p in payments), 2)
    rate = float(bill.hourly_rate) if bill else float(machine.hourly_rate if machine else 0)
    amount = float(bill.amount) if bill else round(rate * int(b.booked_hours), 2)
    due = round(float(bill.amount) - paid, 2) if bill else 0.0
    if not bill:
        state = "Not billed"
    elif due <= 0:
        state = "Paid"
    elif paid > 0:
        state = "Partial"
    else:
        state = "Unpaid"
    return {
        "invoice_no": f"INV-{bill.id:06d}" if bill else f"BKG-{b.id:06d}",
        "has_bill": bill is not None,
        "bill_id": bill.id if bill else None,
        "bill_date": bill.created_at if bill else None,
        "booking_id": b.id, "status": b.status, "date": b.booking_date,
        "start": start, "end": end, "booked_hours": int(b.booked_hours), "notes": b.notes or "",
        "machine_id": b.machine_id,
        "machine_name": machine.name if machine else "",
        "machine_code": (machine.machine_code or f"KE-{machine.id:06d}") if machine else "",
        "hourly_rate": rate,
        "farmer_id": b.farmer_id,
        "farmer_name": farmer.full_name if farmer else "",
        "farmer_phone": farmer.phone if farmer else "",
        "farmer_email": farmer.email if farmer else "",
        "farmer_village": (farmer.village or "") if farmer else "",
        "hours_used": float(bill.hours_used) if bill else None,
        "amount": amount, "paid": paid, "due": due, "payment_state": state,
        "payments": [{"id": p.id, "date": str(p.payment_date), "amount": float(p.amount),
                      "method": p.method, "reference": p.reference or ""} for p in payments],
    }


def _invoice_query(db):
    return db.query(Booking).options(joinedload(Booking.machine), joinedload(Booking.farmer),
                                     joinedload(Booking.bill).joinedload(Bill.payments))


def get_invoice(booking_id, farmer_id=None):
    """Invoice (or booking estimate, when not billed yet) for ONE booking.
    Pass farmer_id to make sure a farmer can only open their own booking."""
    with SessionLocal() as db:
        b = _invoice_query(db).filter(Booking.id == int(booking_id)).first()
        if b is None:
            raise ServiceError("Booking ಕಂಡುಬಂದಿಲ್ಲ.")
        if farmer_id is not None and b.farmer_id != int(farmer_id):
            raise ServiceError("You can only view your own bookings.")
        return _invoice_dict(b)


def get_farmer_invoices(farmer_id):
    """booking_id -> invoice dict for every booking of one farmer (single query)."""
    with SessionLocal() as db:
        rows = _invoice_query(db).filter(Booking.farmer_id == int(farmer_id)).all()
        return {b.id: _invoice_dict(b) for b in rows}


def get_all_invoices():
    """Every booking as an invoice dict (admin/manager exports)."""
    with SessionLocal() as db:
        rows = _invoice_query(db).order_by(Booking.booking_date.desc(), Booking.start_time.desc()).all()
        return [_invoice_dict(b) for b in rows]


def get_billable_bookings():
    """Bookings that can be billed right now: not cancelled, no bill yet, date is today or earlier."""
    with SessionLocal() as db:
        rows = (_invoice_query(db)
                .filter(Booking.status != "Cancelled", Booking.booking_date <= date.today())
                .order_by(Booking.booking_date.desc(), Booking.start_time.desc()).all())
        return [_invoice_dict(b) for b in rows if b.bill is None]


def create_bill_for_farmer(farmer_id, booking_id):
    """A farmer generates the bill for his OWN booking. Hours = the booked hours;
    the admin can still correct the hours (before any payment) with adjust_bill_hours."""
    with SessionLocal() as db:
        booking = db.get(Booking, int(booking_id))
        if booking is None:
            raise ServiceError("Booking ಕಂಡುಬಂದಿಲ್ಲ.")
        if booking.farmer_id != int(farmer_id):
            raise ServiceError("You can only generate bills for your own bookings.")
        hours = float(booking.booked_hours)
    return create_bill(booking_id, hours)


def adjust_bill_hours(bill_id, hours_used):
    """Correct the hours of a bill. Only allowed while no payment has been recorded."""
    hours_used = float(hours_used)
    if hours_used <= 0 or hours_used > 24:
        raise ServiceError("Actual hours 0ಕ್ಕಿಂತ ಹೆಚ್ಚು ಮತ್ತು 24ಕ್ಕಿಂತ ಕಡಿಮೆ ಇರಬೇಕು.")
    with SessionLocal() as db:
        bill = (db.query(Bill).options(joinedload(Bill.booking).joinedload(Booking.machine),
                                       joinedload(Bill.payments))
                .filter(Bill.id == int(bill_id)).with_for_update().first())
        if bill is None:
            raise ServiceError("Bill ಕಂಡುಬಂದಿಲ್ಲ.")
        if bill.payments:
            raise ServiceError("Hours cannot be changed after a payment has been recorded.")
        machine = bill.booking.machine
        machine.service_hours = max(float(machine.service_hours or 0) - float(bill.hours_used) + hours_used, 0.0)
        bill.hours_used = hours_used
        bill.amount = round(hours_used * float(bill.hourly_rate), 2)
        db.commit()
        db.refresh(bill)
        return bill


def get_all_payments():
    """Every recorded payment with farmer / equipment details, newest first."""
    with SessionLocal() as db:
        rows = (db.query(Payment)
                .options(joinedload(Payment.bill).joinedload(Bill.booking).joinedload(Booking.farmer),
                         joinedload(Payment.bill).joinedload(Bill.booking).joinedload(Booking.machine))
                .order_by(Payment.id.desc()).all())
        out = []
        for p in rows:
            bk = p.bill.booking if p.bill else None
            out.append({"payment_id": p.id, "bill_id": p.bill_id, "booking_id": bk.id if bk else None,
                        "date": str(p.payment_date), "amount": float(p.amount), "method": p.method,
                        "reference": p.reference or "",
                        "farmer": bk.farmer.full_name if bk and bk.farmer else "",
                        "equipment": bk.machine.name if bk and bk.machine else ""})
        return out
