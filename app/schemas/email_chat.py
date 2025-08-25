from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from uuid import UUID

class EmailMessage(BaseModel):
    message_id: UUID
    lead_id: UUID
    client_id: UUID
    sender: str
    recipient: str
    subject: str
    body: str
    is_automated: bool
    created_at: datetime

    class Config:
        orm_mode = True

class ConversationHistory(BaseModel):
    lead_id: UUID
    messages: List[EmailMessage]
