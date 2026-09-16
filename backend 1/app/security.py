from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.authentication import decode_access_token
from app.database import SessionLocal
from app.models.user import User

bearer = HTTPBearer(auto_error=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is required.")
    try:
        claims = decode_access_token(credentials.credentials)
        user_id = int(claims["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token.")
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authenticated user no longer exists.")
    return user

class ReviewPrincipal(BaseModel):
    user_id: str
    role: Literal["RADIOLOGIST"]

def require_radiologist(current_user: User = Depends(get_current_user)) -> ReviewPrincipal:
    if current_user.role != "RADIOLOGIST":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Radiologist role is required.")
    return ReviewPrincipal(user_id=str(current_user.id), role="RADIOLOGIST")

class OrthopedicPrincipal(BaseModel):
    user_id: str
    role: Literal["ORTHOPEDIC", "ORTHOPEDIC_SURGEON"]

def require_orthopedic(current_user: User = Depends(get_current_user)) -> OrthopedicPrincipal:
    if current_user.role not in ("ORTHOPEDIC", "ORTHOPEDIC_SURGEON"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Orthopedic role is required.")
    return OrthopedicPrincipal(user_id=str(current_user.id), role=current_user.role)  # type: ignore

class PatientPrincipal(BaseModel):
    user_id: str
    role: Literal["PATIENT"]

def require_patient(current_user: User = Depends(get_current_user)) -> PatientPrincipal:
    if current_user.role != "PATIENT":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Patient role is required.")
    return PatientPrincipal(user_id=str(current_user.id), role="PATIENT")

class ReleasePrincipal(BaseModel):
    user_id: str
    role: Literal["ORTHOPEDIC", "ORTHOPEDIC_SURGEON", "RADIOLOGIST", "CLINICIAN"]

def require_release_authority(current_user: User = Depends(get_current_user)) -> ReleasePrincipal:
    if current_user.role not in ("ORTHOPEDIC", "ORTHOPEDIC_SURGEON", "RADIOLOGIST", "CLINICIAN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clinical authority role is required to release study to patient.",
        )
    return ReleasePrincipal(user_id=str(current_user.id), role=current_user.role)  # type: ignore

