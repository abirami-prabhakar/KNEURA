import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
DATABASE_URL = os.getenv(
    "KNEE_AI_DATABASE_URL",
    f"sqlite:///{(_BACKEND_ROOT / 'knee_ai.db').as_posix()}",
)

_engine_options = (
    {"connect_args": {"check_same_thread": False}}
    if DATABASE_URL.startswith("sqlite")
    else {}
)
engine = create_engine(DATABASE_URL, **_engine_options)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()
