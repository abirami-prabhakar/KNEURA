import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.authentication import hash_password
from app.database import Base, SessionLocal, engine
from app.models.user import User


VALID_ROLES = {"RADIOLOGIST", "ORTHOPEDIC", "ORTHOPEDIC_SURGEON", "PATIENT", "CLINICIAN"}


parser = argparse.ArgumentParser(description="Create a KNEE-AI user explicitly in the existing database.")
parser.add_argument("email")
parser.add_argument("password")
parser.add_argument("role", choices=sorted(VALID_ROLES))
args = parser.parse_args()

Base.metadata.create_all(bind=engine)
db = SessionLocal()
try:
    if db.query(User).filter(User.email == args.email).one_or_none():
        raise SystemExit("A user with that email already exists.")
    user = User(email=args.email, password_hash=hash_password(args.password), role=args.role)
    db.add(user)
    db.commit()
    print(f"Created user {user.email} with role {user.role}.")
finally:
    db.close()
