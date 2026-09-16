from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

from app.database import Base


class Study(Base):
    __tablename__ = "studies"

    id = Column(Integer, primary_key=True, index=True)
    study_id = Column(String, unique=True, index=True, nullable=False)
    # Optional per-study overrides.  When unset, the backend uses the global
    # KNEE_AI_STUDY_ROOT and KNEE_AI_SERIES_METADATA_PATH configuration.
    study_root = Column(String, nullable=True)
    series_metadata_path = Column(String, nullable=True)
    workflow_state = Column(String, nullable=True, index=True)
    patient_id = Column(String, nullable=True, index=True)
    data_mode = Column(String, default="CLINICAL", nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
