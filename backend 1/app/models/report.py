from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Report(Base):
    """Clinical draft report generated from radiologist-validated findings."""

    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    study_id = Column(String, ForeignKey("studies.study_id"), nullable=False, index=True)
    author_id = Column(String, nullable=False, index=True)
    status = Column(String, default="DRAFT", nullable=False)
    draft_content = Column(Text, nullable=False)
    current_version = Column(Integer, default=1, nullable=False)
    approved_version = Column(Integer, nullable=True)
    patient_explanation = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    versions = relationship(
        "ReportVersion",
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="ReportVersion.version_number",
    )


class ReportVersion(Base):
    """Immutable version history for clinical reports."""

    __tablename__ = "report_versions"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    author_id = Column(String, nullable=False, index=True)
    status = Column(String, default="DRAFT", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    report = relationship("Report", back_populates="versions")
