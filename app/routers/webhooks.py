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
    Receive inbound messages from WhatsApp
    Pauses automation when lead replies
    """
    try:
        # Verify signature if needed (e.g., for WhatsApp webhooks)
        if "x-hub-signature" in request.headers:
            # Add signature verification logic here
            signature = request.headers["x-hub-signature"]
            # Verify signature...
            pass
            
        # Parse webhook data (this would depend on your WhatsApp provider)
        # For now, we'll expect a simple JSON format
        import json
        try:
            data = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON"
            )
        
        # Extract lead identifier (phone)
        lead_phone = data.get("phone")
        message_text = data.get("message", "")
        
        if not lead_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number required"
            )
        
        # Find lead by phone
        lead = db.query(Lead).filter(Lead.phone_number == lead_phone).first()
            
        if not lead:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lead not found"
            )
        
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
