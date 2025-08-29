from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import List
from uuid import UUID

from app.database import get_db
from app.models.lead import Lead, ChatSession, ChatHistory
from app.schemas.lead import LeadResponse, LeadUpdate, LeadDetailResponse, ChatMessageResponse
from app.auth import require_client

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("/", response_model=List[LeadResponse])
def list_leads(
    db: Session = Depends(get_db),
    token_data: dict = Depends(require_client)
):
    """Get all leads for the authenticated client"""
    # If admin, show all leads; if client, filter by client_id
    if token_data["role"] == "admin":
        leads = db.query(Lead).all()
    else:
        client_id = UUID(token_data["user_id"])
        leads = db.query(Lead).filter(Lead.client_id == client_id).all()
    
    return leads


@router.get("/{lead_id}", response_model=LeadDetailResponse)
def get_lead_detail(
    lead_id: UUID,
    db: Session = Depends(get_db),
    token_data: dict = Depends(require_client)
):
    """Get full details and chat history for a specific lead"""
    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )
    
    # Check authorization
    if token_data["role"] != "admin" and str(lead.client_id) != token_data["user_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Get chat history for this lead
    chat_sessions = db.query(ChatSession).filter(ChatSession.lead_id == lead_id).all()
    chat_history = []
    
    for session in chat_sessions:
        messages = db.query(ChatHistory).filter(
            ChatHistory.session_id == session.session_id
        ).order_by(ChatHistory.timestamp).all()
        chat_history.extend(messages)
    
    # Sort all messages by timestamp
    chat_history.sort(key=lambda x: x.timestamp)
    
    return LeadDetailResponse(
        lead_id=lead.lead_id,
        client_id=lead.client_id,
        name=lead.name,
        phone_number=lead.phone_number,
        status=lead.status,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
        chat_history=[
            ChatMessageResponse(
                message_id=msg.message_id,
                sender=msg.sender,
                message_text=msg.message_text,
                timestamp=msg.timestamp
            ) for msg in chat_history
        ]
    )


@router.put("/{lead_id}", response_model=LeadResponse)
def update_lead_status(
    lead_id: UUID,
    lead_data: LeadUpdate,
    db: Session = Depends(get_db),
    token_data: dict = Depends(require_client)
):
    """Update a lead's status"""
    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()
    if not lead:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found"
        )
    
    # Check authorization
    if token_data["role"] != "admin" and str(lead.client_id) != token_data["user_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    lead.status = lead_data.status
    db.commit()
    db.refresh(lead)
    return lead
