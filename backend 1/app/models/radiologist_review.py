from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class RadiologistReview(Base):
    """A clinician decision kept independently of immutable AI output rows."""

    __tablename__ = "radiologist_reviews"

    id = Column(Integer, primary_key=True, index=True)
    study_id = Column(String, ForeignKey("studies.study_id"), nullable=False, index=True)
    reviewer_id = Column(String, nullable=False, index=True)
    decision = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    validated_findings = relationship(
        "ValidatedFinding", back_populates="review", cascade="all, delete-orphan"
    )


class ValidatedFinding(Base):
    """A finding explicitly supplied by the radiologist, never inferred from AI scores."""

    __tablename__ = "validated_findings"

    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(Integer, ForeignKey("radiologist_reviews.id"), nullable=False, index=True)
    finding = Column(String, nullable=False)
    outcome = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    is_radiologist_added = Column(Boolean, default=False, nullable=False)

    review = relationship("RadiologistReview", back_populates="validated_findings")
