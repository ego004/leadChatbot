from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
import hmac
import hashlib
from typing import Dict, Any

from app.database import get_db
from app.models.lead import Lead
from app.models.automation import LeadSequenceState, SequenceStatus
from app.config import settings

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def verify_webhook_signature(request_body: bytes, signature: str) -> bool:
    """Verify HMAC signature for webhook security"""
    try:
        expected_signature = hmac.new(
            settings.webhook_secret.encode(),
            request_body,
            hashlib.sha256
        ).hexdigest()
        
        # Remove 'sha256=' prefix if present
        if signature.startswith('sha256='):
            signature = signature[7:]
        
        return hmac.compare_digest(expected_signature, signature)
    except Exception:
        return False


@router.post("/reply")
async def webhook_reply(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Receive inbound messages from email/WhatsApp
    Pauses automation when lead replies
    """
    try:
        # Get request body and signature
        body = await request.body()
        signature = request.headers.get("X-Signature", "")
        
        # Verify signature
        if not verify_webhook_signature(body, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature"
            )
        
        # Parse webhook data (this would depend on your email/WhatsApp provider)
        # For now, we'll expect a simple JSON format
        import json
        try:
            data = json.loads(body.decode())
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON"
            )
        
        # Extract lead identifier (email or phone)
        lead_email = data.get("email")
        lead_phone = data.get("phone")
        message_text = data.get("message", "")
        
        if not (lead_email or lead_phone):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email or phone required"
            )
        
        # Find lead
        lead = None
        if lead_email:
            lead = db.query(Lead).filter(Lead.email == lead_email).first()
        elif lead_phone:
            lead = db.query(Lead).filter(Lead.phone_number == lead_phone).first()
        
        if not lead:
            # Lead not found - could be a new inquiry
            return {"status": "lead_not_found", "message": "Lead not in system"}
        
        # Pause all active automations for this lead
        active_states = db.query(LeadSequenceState).filter(
            LeadSequenceState.lead_id == lead.lead_id,
            LeadSequenceState.status == SequenceStatus.ACTIVE
        ).all()
        
        for state in active_states:
            state.status = SequenceStatus.PAUSED
        
        db.commit()
        
        return {
            "status": "success",
            "message": f"Paused {len(active_states)} active sequences for lead {lead.lead_id}",
            "lead_id": str(lead.lead_id)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Webhook error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )
