from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from app.database import get_db
from app.services.email_chat_service import EmailChatService
from app.models.lead import Lead, EmailMessage
from pydantic import BaseModel
import logging
from app.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/email-chat", tags=["Email Chat Management"], dependencies=[Depends(require_admin)])


class ManualOverrideRequest(BaseModel):
    enabled: bool


class SendEmailRequest(BaseModel):
    to_email: str
    subject: str
    message: str
    lead_id: str


@router.get("/conversations/{client_id}", response_model=List[Dict[str, Any]])
async def get_email_conversations(
    client_id: str,
    active_only: bool = True,
    db: Session = Depends(get_db)
):
    """Get all email conversations for a client"""
    try:
        email_chat_service = EmailChatService(db)
        conversations = email_chat_service.get_email_conversations(client_id, active_only)
        return conversations
    except Exception as e:
        logger.error(f"Error fetching conversations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch email conversations"
        )


@router.get("/conversation/{lead_id}/messages")
async def get_conversation_messages(
    lead_id: str,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """Get email messages for a specific lead conversation"""
    try:
        messages = db.query(EmailMessage).filter(
            EmailMessage.lead_id == lead_id
        ).order_by(EmailMessage.created_at.desc()).limit(limit).all()
        
        return [{
            "message_id": str(msg.message_id),
            "subject": msg.subject,
            "message_text": msg.message_text,
            "is_outbound": msg.is_outbound,
            "status": msg.status,
            "created_at": msg.created_at
        } for msg in reversed(messages)]
        
    except Exception as e:
        logger.error(f"Error fetching conversation messages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch conversation messages"
        )


@router.post("/manual-override/{lead_id}")
async def toggle_manual_override(
    lead_id: str,
    request: ManualOverrideRequest,
    db: Session = Depends(get_db)
):
    """Enable or disable manual override for email conversations"""
    try:
        email_chat_service = EmailChatService(db)
        
        if request.enabled:
            result = email_chat_service.enable_manual_override(lead_id)
        else:
            result = email_chat_service.disable_manual_override(lead_id)
        
        if result["success"]:
            return {"message": result["message"], "manual_override": request.enabled}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result["error"]
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling manual override: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to toggle manual override"
        )


@router.post("/send-manual-email")
async def send_manual_email(
    request: SendEmailRequest,
    db: Session = Depends(get_db)
):
    """Send a manual email (bypasses auto-response)"""
    try:
        # Get lead and client info
        lead = db.query(Lead).filter(Lead.lead_id == request.lead_id).first()
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
        email_chat_service = EmailChatService(db)
        
        # Send manual email
        result = email_chat_service.send_auto_response(
            to_email=request.to_email,
            subject=request.subject,
            message=request.message,
            lead_id=request.lead_id,
            client_id=str(lead.client_id),
            original_message_id=""  # Manual email, no original
        )
        
        if result["success"]:
            return {"message": "Email sent successfully", "message_id": result["message_id"]}
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to send email: {result['error']}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending manual email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send manual email"
        )


@router.post("/start-monitoring")
async def start_email_monitoring(db: Session = Depends(get_db)):
    """Start email monitoring service"""
    try:
        email_chat_service = EmailChatService(db)
        
        if not email_chat_service.is_configured():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email not properly configured. Check IMAP/SMTP settings."
            )
        
        email_chat_service.start_email_monitoring()
        return {"message": "Email monitoring started successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting email monitoring: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start email monitoring"
        )


@router.get("/monitoring-status")
async def get_monitoring_status(db: Session = Depends(get_db)):
    """Get email monitoring status"""
    try:
        email_chat_service = EmailChatService(db)
        
        return {
            "configured": email_chat_service.is_configured(),
            "auto_response_enabled": email_chat_service.auto_response_enabled,
            "response_delay": email_chat_service.response_delay,
            "imap_server": email_chat_service.imap_server,
            "smtp_server": email_chat_service.smtp_server
        }
        
    except Exception as e:
        logger.error(f"Error getting monitoring status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get monitoring status"
        )


@router.get("/stats/{client_id}")
async def get_email_stats(
    client_id: str,
    days: int = 7,
    db: Session = Depends(get_db)
):
    """Get email conversation statistics"""
    try:
        from datetime import datetime, timedelta
        from sqlalchemy import func
        
        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get email statistics
        total_emails = db.query(EmailMessage).join(Lead).filter(
            Lead.client_id == client_id,
            EmailMessage.created_at >= start_date
        ).count()
        
        outbound_emails = db.query(EmailMessage).join(Lead).filter(
            Lead.client_id == client_id,
            EmailMessage.created_at >= start_date,
            EmailMessage.is_outbound == True
        ).count()
        
        inbound_emails = total_emails - outbound_emails
        
        # Get leads with manual override
        manual_override_count = db.query(Lead).filter(
            Lead.client_id == client_id,
            Lead.email_manual_override == True
        ).count()
        
        # Get active conversations (leads with emails in the period)
        active_conversations = db.query(Lead).join(EmailMessage).filter(
            Lead.client_id == client_id,
            EmailMessage.created_at >= start_date
        ).distinct().count()
        
        return {
            "period_days": days,
            "total_emails": total_emails,
            "inbound_emails": inbound_emails,
            "outbound_emails": outbound_emails,
            "active_conversations": active_conversations,
            "manual_override_count": manual_override_count,
            "auto_response_rate": round((outbound_emails / max(inbound_emails, 1)) * 100, 2)
        }
        
    except Exception as e:
        logger.error(f"Error getting email stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get email statistics"
        )
