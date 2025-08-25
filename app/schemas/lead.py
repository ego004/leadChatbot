from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from app.models.lead import LeadStatus, SenderType


class LeadCreate(BaseModel):
    name: str
    email: EmailStr
    phone_number: Optional[str] = None


class LeadUpdate(BaseModel):
    status: LeadStatus


class LeadResponse(BaseModel):
    lead_id: UUID
    client_id: UUID
    name: str
    email: str
    phone_number: Optional[str]
    status: LeadStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatMessageResponse(BaseModel):
    message_id: UUID
    sender: SenderType
    message_text: str
    timestamp: datetime

    class Config:
        from_attributes = True


class LeadDetailResponse(LeadResponse):
    chat_history: List[ChatMessageResponse] = []


class ChatRequest(BaseModel):
    client_id: UUID
    session_id: Optional[UUID] = None
    query: str


class ChatResponse(BaseModel):
    session_id: UUID
    response_type: str  # "text" or "lead_captured"
    data: str
