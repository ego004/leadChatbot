from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime
from uuid import UUID
from app.models.client import IngestionStatus


class ClientCreate(BaseModel):
    name: str
    website_url: str


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    website_url: Optional[str] = None
    system_prompt: Optional[str] = None


class ClientResponse(BaseModel):
    client_id: UUID
    name: str
    website_url: str
    system_prompt: Optional[str]
    ingestion_status: IngestionStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
