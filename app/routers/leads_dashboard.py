from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from app.database import get_db
from app.models.client import Client
from app.models.lead import Lead, ChatSession, ChatHistory
from app.models.knowledge_base import ClientDeployment
from app.auth import require_client_or_admin

router = APIRouter(
    prefix="/api/client/dashboard",
    tags=["Client Dashboard"],
    dependencies=[Depends(require_client_or_admin)]
)


@router.get("/client/{client_id}/leads")
def get_client_leads(
    client_id: UUID,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    token_data: dict = Depends(require_client_or_admin)
):
    """
    Authenticated endpoint for clients to view their leads.
    Admins can access any client; clients can only access their own client_id.
    """
    # Authorization: client must match their own client_id unless admin
    if token_data["role"] != "admin" and token_data["user_id"] != str(client_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    # Verify client exists and is deployed
    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == client_id,
        ClientDeployment.is_deployed == True
    ).first()
    
    if not deployment:
        raise HTTPException(status_code=403, detail="Dashboard not available")
    
    # Get leads with optional status filter
    query = db.query(Lead).filter(Lead.client_id == client_id)
    
    if status_filter:
        from app.models.lead import LeadStatus
        try:
            status_enum = LeadStatus(status_filter)
            query = query.filter(Lead.status == status_enum)
        except ValueError:
            pass  # Invalid status, ignore filter
    
    leads = query.order_by(Lead.created_at.desc()).all()
    
    result = []
    for lead in leads:
        # Get latest chat session for this lead
        latest_session = db.query(ChatSession).filter(
            ChatSession.lead_id == lead.lead_id
        ).order_by(ChatSession.created_at.desc()).first()
        
        # Get message count
        message_count = 0
        if latest_session:
            message_count = db.query(ChatHistory).filter(
                ChatHistory.session_id == latest_session.session_id
            ).count()
        
        result.append({
            "lead_id": lead.lead_id,
            "name": lead.name or "Anonymous",
            "email": lead.email,
            "phone_number": lead.phone_number,
            "status": lead.status.value,
            "whatsapp_manual_override": lead.whatsapp_manual_override,
            "message_count": message_count,
            "created_at": lead.created_at,
            "last_activity": latest_session.created_at if latest_session else lead.created_at
        })
    
    return {
        "client_name": client.name,
        "total_leads": len(result),
        "leads": result
    }


@router.get("/client/{client_id}/leads/{lead_id}/conversation")
def get_lead_conversation(
    client_id: UUID,
    lead_id: UUID,
    db: Session = Depends(get_db),
    token_data: dict = Depends(require_client_or_admin)
):
    """Get full conversation history for a specific lead"""
    # Authorization: client must match their own client_id unless admin
    if token_data["role"] != "admin" and token_data["user_id"] != str(client_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    # Verify lead belongs to client
    lead = db.query(Lead).filter(
        Lead.lead_id == lead_id,
        Lead.client_id == client_id
    ).first()
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Get all chat sessions for this lead
    sessions = db.query(ChatSession).filter(
        ChatSession.lead_id == lead_id
    ).order_by(ChatSession.created_at).all()
    
    conversation = []
    for session in sessions:
        messages = db.query(ChatHistory).filter(
            ChatHistory.session_id == session.session_id
        ).order_by(ChatHistory.timestamp).all()
        
        for msg in messages:
            conversation.append({
                "message_id": msg.message_id,
                "sender": msg.sender.value,
                "message": msg.message_text,
                "timestamp": msg.timestamp,
                "session_id": session.session_id
            })
    
    return {
        "lead": {
            "lead_id": lead.lead_id,
            "name": lead.name or "Anonymous",
            "email": lead.email,
            "phone_number": lead.phone_number,
            "status": lead.status.value,
            "whatsapp_manual_override": lead.whatsapp_manual_override,
            "created_at": lead.created_at
        },
        "conversation": conversation,
        "total_messages": len(conversation)
    }


@router.get("/client/{client_id}/stats")
def get_client_stats(
    client_id: UUID,
    db: Session = Depends(get_db),
    token_data: dict = Depends(require_client_or_admin)
):
    """Get basic statistics for client dashboard"""
    # Authorization: client must match their own client_id unless admin
    if token_data["role"] != "admin" and token_data["user_id"] != str(client_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    from app.models.lead import LeadStatus
    from sqlalchemy import func
    from datetime import datetime, timedelta
    
    # Total leads
    total_leads = db.query(Lead).filter(Lead.client_id == client_id).count()
    
    # Leads by status
    status_counts = db.query(
        Lead.status, func.count(Lead.lead_id)
    ).filter(Lead.client_id == client_id).group_by(Lead.status).all()
    
    status_breakdown = {status.value: 0 for status in LeadStatus}
    for status, count in status_counts:
        status_breakdown[status.value] = count
    
    # Recent leads (last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    recent_leads = db.query(Lead).filter(
        Lead.client_id == client_id,
        Lead.created_at >= week_ago
    ).count()
    
    # Total conversations
    total_conversations = db.query(ChatSession).filter(
        ChatSession.client_id == client_id
    ).count()
    
    return {
        "client_name": client.name,
        "total_leads": total_leads,
        "recent_leads_7_days": recent_leads,
        "total_conversations": total_conversations,
        "leads_by_status": status_breakdown,
        "dashboard_url": f"https://your-domain.com/dashboard/{client_id}"
    }
