from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base


class OrthopedicReview(Base):
    """Orthopedic clinician review of an approved study."""

    __tablename__ = "orthopedic_reviews"

    id = Column(Integer, primary_key=True, index=True)
    study_id = Column(String, ForeignKey("studies.study_id"), nullable=False, index=True)
    reviewer_id = Column(String, nullable=False, index=True)
    assessment = Column(Text, nullable=False)
    recommendation = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    patient_information_approved = Column(Boolean, default=False, nullable=True)
    approved_followup_info = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
