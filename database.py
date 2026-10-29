import os
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import (
    create_engine, String, Integer, Float, Date, Time, DateTime, ForeignKey,
    Text, Boolean, UniqueConstraint, inspect, text
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, relationship

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///farm_equipment.db").strip()
engine_kwargs = {"pool_pre_ping": True, "pool_recycle": 1800}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    address: Mapped[str] = mapped_column(String(255), default="")
    village: Mapped[str] = mapped_column(String(100), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="farmer")
    preferred_language: Mapped[str] = mapped_column(String(12), default="English")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Machine(Base):
    __tablename__ = "machines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_code: Mapped[str | None] = mapped_column(String(24), unique=True, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(60), index=True)
    hourly_rate: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="Available", index=True)
    service_hours: Mapped[float] = mapped_column(Float, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    approval_status: Mapped[str] = mapped_column(String(20), default="Approved", index=True)
    location: Mapped[str] = mapped_column(String(180), default="")
    contact_phone: Mapped[str] = mapped_column(String(10), default="")
    owner: Mapped[User | None] = relationship()

class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    farmer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    booking_date: Mapped[object] = mapped_column(Date, index=True)
    start_time: Mapped[object] = mapped_column(Time)
    booked_hours: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="Confirmed", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    machine: Mapped[Machine] = relationship()
    farmer: Mapped[User] = relationship()
    bill: Mapped["Bill | None"] = relationship(back_populates="booking", uselist=False)

class Bill(Base):
    __tablename__ = "bills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), unique=True)
    hours_used: Mapped[float] = mapped_column(Float)
    hourly_rate: Mapped[float] = mapped_column(Float)
    amount: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    booking: Mapped[Booking] = relationship(back_populates="bill")
    payments: Mapped[list["Payment"]] = relationship(back_populates="bill")

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    payment_date: Mapped[object] = mapped_column(Date, default=datetime.utcnow)
    method: Mapped[str] = mapped_column(String(30), default="Cash")
    reference: Mapped[str] = mapped_column(String(100), default="")
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    bill: Mapped[Bill] = relationship(back_populates="payments")

class EmailOTP(Base):
    __tablename__ = "email_otps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    code_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ServiceLog(Base):
    """NEW: one row each time a machine is serviced. The 100-hour reminder counts from the latest row."""
    __tablename__ = "service_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"), index=True)
    hours_at_service: Mapped[float] = mapped_column(Float, default=0)
    note: Mapped[str] = mapped_column(String(255), default="")
    serviced_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    serviced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def init_db():
    """Create missing tables and apply safe additive migrations to existing MySQL/SQLite DBs."""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "machines" in tables:
        columns = {col["name"] for col in inspector.get_columns("machines")}
        additions = {
            "machine_code": "VARCHAR(24) NULL",
            "owner_id": "INTEGER NULL",
            "approval_status": "VARCHAR(20) NOT NULL DEFAULT 'Approved'",
            "location": "VARCHAR(180) NOT NULL DEFAULT ''",
            "contact_phone": "VARCHAR(10) NOT NULL DEFAULT ''",
        }
        for column, definition in additions.items():
            if column not in columns:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE machines ADD COLUMN {column} {definition}"))
        # Give every old and new machine a stable human-readable registration ID.
        with SessionLocal() as db:
            rows = db.query(Machine).filter((Machine.machine_code.is_(None)) | (Machine.machine_code == "")).all()
            for machine in rows:
                machine.machine_code = f"KE-{machine.id:06d}"
            db.commit()
        indexes = {idx.get("name") for idx in inspect(engine).get_indexes("machines")}
        if "ix_machines_machine_code" not in indexes:
            try:
                with engine.begin() as conn:
                    conn.execute(text("CREATE UNIQUE INDEX ix_machines_machine_code ON machines (machine_code)"))
            except Exception:
                # A pre-existing duplicate code should not prevent the app from starting;
                # booking safety is still enforced by machine_id and transactional checks.
                pass
    with SessionLocal() as db:
        if db.query(Machine).count() == 0:
            seeds = [
                Machine(name="Tractor", hourly_rate=600, description="General field preparation and transport.", approval_status="Approved"),
                Machine(name="Rotavator", hourly_rate=500, description="Soil tilling and seedbed preparation.", approval_status="Approved"),
                Machine(name="Power tiller", hourly_rate=400, description="Small farm cultivation.", approval_status="Approved"),
                Machine(name="Sprayer", hourly_rate=250, description="Crop spraying equipment.", approval_status="Approved"),
                Machine(name="Harvester", hourly_rate=1500, description="Harvesting support.", approval_status="Approved"),
            ]
            db.add_all(seeds)
            db.flush()
            for machine in seeds:
                machine.machine_code = f"KE-{machine.id:06d}"
            db.commit()
