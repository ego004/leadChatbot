from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import timedelta
from app.config import settings
from app.auth import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def admin_login(payload: LoginRequest):
    if not settings.admin_email or not settings.admin_password:
        raise HTTPException(status_code=500, detail="Admin credentials not configured")
    if payload.email != settings.admin_email or payload.password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token_expires = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    token = create_access_token({"sub": payload.email, "role": "admin"}, expires_delta=access_token_expires)
    return {"access_token": token, "token_type": "bearer"}
