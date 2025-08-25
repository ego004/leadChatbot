from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.client import Client
from app.models.lead import Lead, LeadStatus, EmailMessage
from app.models.knowledge_base import ClientDeployment
from app.services.lead_service import LeadService
from app.services.email_service import EmailService
from app.schemas.email_chat import EmailMessage as EmailMessageSchema
from typing import Optional, List
from datetime import datetime, timedelta, date
from sqlalchemy import func
from app.models.analytics import ClientDailyStats
import jwt
import os
from app.config import settings

router = APIRouter(prefix="/api/client", tags=["Client Dashboard"])
security = HTTPBearer()

# Use application settings (loaded from .env via pydantic) for JWT configuration
# This ensures consistency with tokens minted by scripts/tests using the same secret
SECRET_KEY = settings.jwt_secret_key or os.getenv("JWT_SECRET_KEY", "your-secret-key")
ALGORITHM = settings.jwt_algorithm if getattr(settings, "jwt_algorithm", None) else "HS256"

def create_access_token(client_id: str, expires_delta: Optional[timedelta] = None):
    """Create JWT token for client authentication"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
    
    to_encode = {"sub": client_id, "exp": expire}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_client_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify client JWT token"""
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        client_id: str = payload.get("sub")
        if client_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return client_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@router.post("/login")
async def client_login(
    company_name: str,
    contact_email: str,
    db: Session = Depends(get_db)
):
    """Simple client login (in production, use proper authentication)"""
    
    client = db.query(Client).filter(
        Client.name == company_name,
        Client.contact_email == contact_email
    ).first()
    
    if not client:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Create access token
    access_token = create_access_token(str(client.client_id))
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "client_id": str(client.client_id),
        "company_name": client.name
    }

@router.get("/leads")
async def get_client_leads(
    status_filter: Optional[str] = None,
    client_id: str = Depends(verify_client_token),
    db: Session = Depends(get_db)
):
    """Get all leads for authenticated client"""
    
    lead_service = LeadService(db)
    
    # Convert status filter if provided
    status_enum = None
    if status_filter:
        try:
            status_enum = LeadStatus(status_filter.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid status filter")
    
    leads = lead_service.get_leads_for_client(client_id, status_enum)
    
    # Format leads with additional info
    formatted_leads = []
    for lead in leads:
        lead_data = lead_service.get_lead_with_email_history(str(lead.lead_id))
        formatted_leads.append({
            "lead_id": str(lead.lead_id),
            "name": lead.name,
            "email": lead.email,
            "phone_number": lead.phone_number,
            "status": lead.status.value,
            "email_manual_override": lead.email_manual_override,
            "created_at": lead.created_at,
            "updated_at": lead.updated_at,
            "email_messages_count": len(lead_data["email_messages"]) if lead_data else 0,
            "last_email_sent": lead.last_email_sent
        })
    
    return {
        "leads": formatted_leads,
        "total_count": len(formatted_leads)
    }

@router.get("/leads/{lead_id}")
async def get_lead_details(
    lead_id: str,
    client_id: str = Depends(verify_client_token),
    db: Session = Depends(get_db)
):
    """Get detailed lead information including chat and WhatsApp history"""
    
    # Verify lead belongs to client
    lead = db.query(Lead).filter(
        Lead.lead_id == lead_id,
        Lead.client_id == client_id
    ).first()
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    lead_service = LeadService(db)
    lead_data = lead_service.get_lead_with_email_history(lead_id)
    
    # Get chat history
    chat_context = lead_service.get_chat_history_context(lead_id, limit=50)
    
    return {
        "lead": {
            "lead_id": str(lead.lead_id),
            "name": lead.name,
            "email": lead.email,
            "phone_number": lead.phone_number,
            "status": lead.status.value,
            "email_manual_override": lead.email_manual_override,
            "created_at": lead.created_at,
            "updated_at": lead.updated_at
        },
        "chat_history": chat_context,
        "email_messages": [
            {
                "message_id": str(msg.message_id),
                "subject": msg.subject,
                "message_text": msg.message_text,
                "is_outbound": msg.is_outbound,
                "status": msg.status,
                "created_at": msg.created_at
            }
            for msg in lead_data["email_messages"]
        ] if lead_data else []
    }

@router.post("/leads/{lead_id}/send-email")
async def send_manual_email(
    lead_id: str,
    subject: str,
    message: str,
    client_id: str = Depends(verify_client_token),
    db: Session = Depends(get_db)
):
    """Send manual email to lead"""
    
    # Verify lead belongs to client
    lead = db.query(Lead).filter(
        Lead.lead_id == lead_id,
        Lead.client_id == client_id
    ).first()
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    if not lead.email:
        raise HTTPException(status_code=400, detail="Lead has no email address")
    
    # Send email
    email_service = EmailService(db)
    result = email_service.send_email(
        to_email=lead.email,
        subject=subject,
        message=message,
        lead_id=lead_id,
        client_id=client_id
    )
    
    if result["success"]:
        # Update lead's last email sent
        lead.last_email_sent = message
        db.commit()
        
        return {
            "success": True,
            "message": "Email sent successfully",
            "message_id": result["message_id"]
        }
    else:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {result['error']}")

@router.post("/leads/{lead_id}/toggle-manual-override")
async def toggle_email_manual_override(
    lead_id: str,
    enable: bool,
    client_id: str = Depends(verify_client_token),
    db: Session = Depends(get_db)
):
    """Enable/disable manual override for email automation"""
    
    # Verify lead belongs to client
    lead = db.query(Lead).filter(
        Lead.lead_id == lead_id,
        Lead.client_id == client_id
    ).first()
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    lead_service = LeadService(db)
    updated_lead = lead_service.set_email_manual_override(lead_id, enable)
    
    return {
        "success": True,
        "message": f"Manual override {'enabled' if enable else 'disabled'}",
        "email_manual_override": updated_lead.email_manual_override
    }

@router.put("/leads/{lead_id}/status")
async def update_lead_status(
    lead_id: str,
    status: str,
    client_id: str = Depends(verify_client_token),
    db: Session = Depends(get_db)
):
    """Update lead status"""
    
    # Verify lead belongs to client
    lead = db.query(Lead).filter(
        Lead.lead_id == lead_id,
        Lead.client_id == client_id
    ).first()
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Validate status
    try:
        status_enum = LeadStatus(status.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    lead_service = LeadService(db)
    updated_lead = lead_service.update_lead_status(lead_id, status_enum)
    
    return {
        "success": True,
        "message": "Lead status updated",
        "status": updated_lead.status.value
    }

@router.get("/dashboard/stats")
async def get_dashboard_stats(
    client_id: str = Depends(verify_client_token),
    db: Session = Depends(get_db)
):
    """Get dashboard statistics for client"""
    
    # Get lead counts by status
    total_leads = db.query(Lead).filter(Lead.client_id == client_id).count()
    new_leads = db.query(Lead).filter(
        Lead.client_id == client_id,
        Lead.status == LeadStatus.NEW
    ).count()
    qualified_leads = db.query(Lead).filter(
        Lead.client_id == client_id,
        Lead.status == LeadStatus.QUALIFIED
    ).count()
    contacted_leads = db.query(Lead).filter(
        Lead.client_id == client_id,
        Lead.status == LeadStatus.CONTACTED
    ).count()
    
    # Get deployment status
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == client_id
    ).first()

    # Get email stats for the last 30 days
    start_date = datetime.utcnow() - timedelta(days=30)
    total_emails = db.query(EmailMessage).join(Lead).filter(
        Lead.client_id == client_id,
        EmailMessage.created_at >= start_date
    ).count()
    outbound_emails = db.query(EmailMessage).join(Lead).filter(
        Lead.client_id == client_id,
        EmailMessage.created_at >= start_date,
        EmailMessage.is_outbound == True
    ).count()
    active_conversations = db.query(Lead).join(EmailMessage).filter(
        Lead.client_id == client_id,
        EmailMessage.created_at >= start_date
    ).distinct().count()
    
    return {
        "stats": {
            "total_leads": total_leads,
            "new_leads": new_leads,
            "qualified_leads": qualified_leads,
            "contacted_leads": contacted_leads,
            "emails_sent_30d": outbound_emails,
            "emails_received_30d": total_emails - outbound_emails,
            "active_conversations_30d": active_conversations
        },
        "deployment": {
            "is_deployed": deployment.is_deployed if deployment else False,
            "custom_client_id": deployment.custom_client_id if deployment else None,
            "deployment_url": deployment.deployment_url if deployment else None
        }
    }

def _timeframe_to_range(tf: str | None, start: Optional[str], end: Optional[str]) -> tuple[date, date]:
    """Convert timeframe or explicit ISO dates to [start_date, end_date] inclusive in UTC date.
    tf options: today, 7d, 30d, this_week, this_month, last_month, all
    If start/end provided (YYYY-MM-DD), they override tf.
    """
    if start and end:
        try:
            s = datetime.strptime(start, "%Y-%m-%d").date()
            e = datetime.strptime(end, "%Y-%m-%d").date()
            return s, e
        except Exception:
            pass
    today = datetime.utcnow().date()
    if not tf or tf == "today":
        return today, today
    if tf == "7d":
        return today - timedelta(days=6), today
    if tf == "30d":
        return today - timedelta(days=29), today
    if tf == "this_week":
        # week starts Monday
        start_week = today - timedelta(days=today.weekday())
        return start_week, today
    if tf == "this_month":
        start_month = today.replace(day=1)
        return start_month, today
    if tf == "last_month":
        first_this_month = today.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        start_last_month = last_month_end.replace(day=1)
        return start_last_month, last_month_end
    if tf == "all":
        # effectively no lower bound; use far past
        return date(1970, 1, 1), today
    # default fallback 30d
    return today - timedelta(days=29), today


@router.get("/analytics/summary")
async def analytics_summary(
    timeframe: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    client_id: str = Depends(verify_client_token),
    db: Session = Depends(get_db)
):
    """Return totals for the timeframe (or explicit start/end dates).
    timeframe options: today, 7d, 30d, this_week, this_month, last_month, all
    start_date/end_date format: YYYY-MM-DD
    """
    start_d, end_d = _timeframe_to_range(timeframe, start_date, end_date)

    agg = db.query(
        func.coalesce(func.sum(ClientDailyStats.messages_user), 0),
        func.coalesce(func.sum(ClientDailyStats.messages_bot), 0),
        func.coalesce(func.sum(ClientDailyStats.sessions_started), 0),
        func.coalesce(func.sum(ClientDailyStats.leads_created), 0),
        func.coalesce(func.sum(ClientDailyStats.leads_qualified), 0),
        func.coalesce(func.sum(ClientDailyStats.contacts_captured), 0),
    ).filter(
        ClientDailyStats.client_id == client_id,
        ClientDailyStats.date >= start_d,
        ClientDailyStats.date <= end_d,
    ).one()

    return {
        "timeframe": {
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
        },
        "totals": {
            "messages_user": int(agg[0]),
            "messages_bot": int(agg[1]),
            "sessions_started": int(agg[2]),
            "leads_created": int(agg[3]),
            "leads_qualified": int(agg[4]),
            "contacts_captured": int(agg[5]),
        },
    }


@router.get("/analytics/daily")
async def analytics_daily(
    days: int = 30,
    client_id: str = Depends(verify_client_token),
    db: Session = Depends(get_db)
):
    """Return last N days of daily counters for charting."""
    days = max(1, min(days, 180))
    end_d = datetime.utcnow().date()
    start_d = end_d - timedelta(days=days - 1)

    rows = db.query(ClientDailyStats).filter(
        ClientDailyStats.client_id == client_id,
        ClientDailyStats.date >= start_d,
        ClientDailyStats.date <= end_d,
    ).order_by(ClientDailyStats.date.asc()).all()

    # index by date for gaps
    by_date = {r.date: r for r in rows}
    series = []
    cur = start_d
    while cur <= end_d:
        r = by_date.get(cur)
        series.append({
            "date": cur.isoformat(),
            "messages_user": int(getattr(r, "messages_user", 0) or 0) if r else 0,
            "messages_bot": int(getattr(r, "messages_bot", 0) or 0) if r else 0,
            "sessions_started": int(getattr(r, "sessions_started", 0) or 0) if r else 0,
            "leads_created": int(getattr(r, "leads_created", 0) or 0) if r else 0,
            "leads_qualified": int(getattr(r, "leads_qualified", 0) or 0) if r else 0,
            "contacts_captured": int(getattr(r, "contacts_captured", 0) or 0) if r else 0,
        })
        cur += timedelta(days=1)

    return {
        "timeframe": {"start_date": start_d.isoformat(), "end_date": end_d.isoformat()},
        "daily": series,
    }

@router.get("/leads/{lead_id}/conversation", response_model=List[EmailMessageSchema])
async def get_lead_conversation(
    lead_id: str,
    client_id: str = Depends(verify_client_token),
    db: Session = Depends(get_db)
):
    """Get the full email conversation history for a lead."""
    # Verify lead belongs to client
    lead = db.query(Lead).filter(
        Lead.lead_id == lead_id,
        Lead.client_id == client_id
    ).first()
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    messages = db.query(EmailMessage).filter(EmailMessage.lead_id == lead_id).order_by(EmailMessage.created_at.asc()).all()
    
    return messages
