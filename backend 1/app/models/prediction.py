from sqlalchemy import Column, Integer, String, Float, ForeignKey

from app.database import Base


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    study_id = Column(String, ForeignKey("studies.study_id"), nullable=False)

    label = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
