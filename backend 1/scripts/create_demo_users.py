"""Explicit local bootstrap; never seed users during API startup."""
import getpass
import os
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.authentication import hash_password
from app.database import Base, SessionLocal, engine
from app import models
from app.models.user import User

ACCOUNTS = {
    "radiologist@kneura.local": "RADIOLOGIST",
    "orthopedic@kneura.local": "ORTHOPEDIC_SURGEON",
    "patient@kneura.local": "PATIENT",
}


def bootstrap():
    if engine.url.get_backend_name() != "sqlite" or not str(engine.url.database).endswith("kneura_demo.db"):
        raise SystemExit("Demo bootstrap requires an explicit SQLite KNEE_AI_DATABASE_URL ending in kneura_demo.db.")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        missing = [email for email in ACCOUNTS if not db.query(User).filter_by(email=email).first()]
        if missing:
            password = os.getenv("KNEE_AI_DEMO_PASSWORD") or getpass.getpass("Choose a local demo password (minimum 12 characters): ")
            if len(password) < 12:
                raise SystemExit("Use at least 12 characters for the demo password.")
            for email in missing:
                db.add(User(email=email, password_hash=hash_password(password), role=ACCOUNTS[email]))
            db.flush()
        for email, role in ACCOUNTS.items():
            if db.query(User).filter_by(email=email).one().role != role:
                raise SystemExit("Existing demo user role differs; no users will be overwritten.")
        db.commit()
    print("Local demo users ready; existing passwords and workflow state preserved.")


if __name__ == "__main__":
    bootstrap()
