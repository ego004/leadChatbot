from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.lead import Lead, ChatSession, ChatHistory, SenderType, LeadStatus
from app.models.client import Client
from app.models.knowledge_base import ClientDeployment
from app.services.vector_store_service import VectorStoreService
from app.services.gemini_service import GeminiService
from app.services.lead_service import LeadService
from app.services.analytics_service import increment_stats
import uuid
from typing import Optional
import time
import json
from collections import defaultdict
import os

router = APIRouter(prefix="/api/chat", tags=["Chat"])
security = HTTPBearer()

# Rate limiting storage (in production, use Redis)
rate_limit_storage = defaultdict(list)
# Toggle via env var
RATE_LIMIT_ENABLED = os.getenv("CHAT_RATE_LIMIT_ENABLED", "true").lower() == "true"
# Default to requiring a deployment token in production-like environments
REQUIRE_DEPLOYMENT_TOKEN = os.getenv("CHAT_REQUIRE_DEPLOYMENT_TOKEN", "true").lower() == "true"

def check_rate_limit(client_ip: str, limit: int = 10, window: int = 60) -> bool:
    """Check if client has exceeded rate limit"""
    now = time.time()
    
    # Clean old entries
    rate_limit_storage[client_ip] = [
        timestamp for timestamp in rate_limit_storage[client_ip]
        if now - timestamp < window
    ]
    
    # Check if limit exceeded
    if len(rate_limit_storage[client_ip]) >= limit:
        return False
    
    # Add current request
    rate_limit_storage[client_ip].append(now)
    return True

@router.post("/{custom_client_id}/message")
async def send_message(
    custom_client_id: str,
    message: str,
    request: Request,
    session_id: Optional[str] = None,
    lead_name: Optional[str] = None,
    lead_email: Optional[str] = None,
    lead_phone: Optional[str] = None,
    top_k: int = 5,
    return_sources: bool = False,
    db: Session = Depends(get_db)
):
    """Protected chat endpoint with rate limiting and lead qualification.

    Query params:
    - message: user message
    - session_id, lead_*: optional tracking
    - top_k: number of KB chunks to retrieve (default 5)
    - return_sources: include retrieved source snippets and metadata in response
    """
    
    # Rate limiting (optional)
    if RATE_LIMIT_ENABLED:
        client_ip = request.client.host
        if not check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    # Get client by custom ID
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.custom_client_id == custom_client_id,
        ClientDeployment.is_deployed == True
    ).first()
    
    if not deployment:
        raise HTTPException(status_code=404, detail="Chatbot not found or not deployed")
    
    # Optional per-client token auth
    if REQUIRE_DEPLOYMENT_TOKEN:
        provided = request.headers.get("x-deployment-token")
        if not provided:
            auth_header = request.headers.get("authorization") or ""
            if auth_header.lower().startswith("bearer "):
                provided = auth_header.split(" ", 1)[1].strip()
        stored = deployment.deployment_api_token
        if not stored:
            raise HTTPException(status_code=403, detail="Deployment token not configured")
        if not provided or provided != stored:
            raise HTTPException(status_code=401, detail="Invalid or missing deployment token")

    client_id = str(deployment.client_id)
    
    # Initialize services
    lead_service = LeadService(db)
    
    # Get or create lead (with deduplication & creation flag)
    lead, lead_created = lead_service.find_or_create_lead_with_flag(
        client_id=client_id,
        phone_number=lead_phone,
        name=lead_name,
        browser_session_id=session_id
    )
    if lead_created:
        try:
            increment_stats(db, client_id, sessions_started=1)
        except Exception:
            pass
    
    # Get or create chat session
    if session_id:
        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id,
            ChatSession.client_id == client_id
        ).first()
        if not session:
            session = ChatSession(
                client_id=client_id, 
                lead_id=str(lead.lead_id),
                session_id=session_id
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            # Count a unique impression (new chat session)
            try:
                increment_stats(db, client_id, sessions_started=1)
            except Exception:
                pass
    else:
        session = ChatSession(client_id=client_id, lead_id=str(lead.lead_id))
        db.add(session)
        db.commit()
        db.refresh(session)
        # Count a unique impression (new chat session)
        try:
            increment_stats(db, client_id, sessions_started=1)
        except Exception:
            pass
    
    # Save user message
    user_message = ChatHistory(
        session_id=session.session_id,
        sender=SenderType.USER,
        message_text=message
    )
    db.add(user_message)
    # Increment user message counter
    try:
        increment_stats(db, client_id, messages_user=1)
    except Exception:
        pass
    
    # Get relevant context from knowledge base
    # IngestionService stores vectors in collection name prefixed with "client_"
    vector_store = VectorStoreService(collection_name=f"client_{client_id}")
    # Retrieve KB context
    try:
        k = max(1, min(int(top_k), 20))
    except Exception:
        k = 5
    context_results = vector_store.query(message, k=k)
    context = "\n".join([doc.page_content for doc in context_results])
    
    # Get chat history for context
    chat_history = []
    recent_messages = db.query(ChatHistory).filter(
        ChatHistory.session_id == session.session_id
    ).order_by(ChatHistory.timestamp.desc()).limit(10).all()
    
    for msg in reversed(recent_messages):
        chat_history.append({
            "sender": msg.sender.value,
            "message": msg.message_text
        })
    
    # Generate AI response with Gemini and tools
    gemini_service = GeminiService()
    system_prompt = deployment.website_system_prompt or "You are a helpful AI assistant."
    
    ai_result = await gemini_service.generate_response(
        message=message, 
        context=context, 
        system_prompt=system_prompt,
        chat_history=chat_history
    )
    
    ai_response = ai_result["response"]
    tool_results = ai_result["tool_results"]
    
    # Save AI response
    bot_message = ChatHistory(
        session_id=session.session_id,
        sender=SenderType.BOT,
        message_text=ai_response
    )
    db.add(bot_message)
    # Increment bot message counter
    try:
        increment_stats(db, client_id, messages_bot=1)
    except Exception:
        pass
    
    # Handle tool results
    lead_qualified = False
    contact_captured = False
    
    if tool_results.get("lead_qualification"):
        qualification = tool_results["lead_qualification"]
        if qualification == "QUALIFIED":
            # Only treat as QUALIFIED if we have a reachable contact (email or phone)
            qp_email = (lead_email or "").strip()
            qp_phone = (lead_phone or "").strip()
            has_reachable_contact = bool((lead.email or lead.phone_number) or qp_email or qp_phone)
            if has_reachable_contact:
                lead_qualified = True
                lead_service.update_lead_status(str(lead.lead_id), LeadStatus.QUALIFIED)
                try:
                    increment_stats(db, client_id, leads_qualified=1)
                except Exception:
                    pass
            else:
                # Buying signals only → keep in CONTACTED until contact info is captured
                try:
                    lead_service.update_lead_status(str(lead.lead_id), LeadStatus.CONTACTED)
                except Exception:
                    pass
        elif qualification == "POTENTIAL":
            # Nurture state: mark as contacted but do not treat as qualified yet
            try:
                lead_service.update_lead_status(str(lead.lead_id), LeadStatus.CONTACTED)
            except Exception:
                pass
    
    if tool_results.get("contact_info"):
        contact_info = tool_results["contact_info"]
        # Prefer tool values but allow query params to supplement missing fields
        name_val_tool = (contact_info.get("name") or "").strip()
        email_val_tool = (contact_info.get("email") or "").strip()
        phone_val_tool = (contact_info.get("phone") or "").strip()
        qp_name = (lead_name or "").strip()
        qp_email = (lead_email or "").strip()
        qp_phone = (lead_phone or "").strip()
        name_val = name_val_tool or qp_name
        email_val = email_val_tool or qp_email
        phone_val = phone_val_tool or qp_phone
        contact_captured = bool(name_val or email_val or phone_val)

        # Update lead with captured/supplemented contact info
        if name_val and not lead.name:
            lead.name = name_val
        if email_val and not lead.email:
            lead.email = email_val
        if phone_val and not lead.phone_number:
            lead.phone_number = phone_val

        # If we have a reachable contact (email or phone), auto-qualify once
        if (email_val or phone_val) and lead.status != LeadStatus.QUALIFIED:
            lead_service.update_lead_status(str(lead.lead_id), LeadStatus.QUALIFIED)
            lead_qualified = True
            try:
                increment_stats(db, client_id, leads_qualified=1)
            except Exception:
                pass

        db.commit()
        # Increment contacts captured analytics if any contact field was captured
        if contact_captured:
            try:
                increment_stats(db, client_id, contacts_captured=1)
            except Exception:
                pass
    else:
        # If no tool-captured contact info, but query params provided, treat as capture
        qp_name = (lead_name or "").strip()
        qp_email = (lead_email or "").strip()
        qp_phone = (lead_phone or "").strip()
        if qp_name or qp_email or qp_phone:
            # Update lead fields from query params
            if qp_name and not lead.name:
                lead.name = qp_name
            if qp_email and not lead.email:
                lead.email = qp_email
            if qp_phone and not lead.phone_number:
                lead.phone_number = qp_phone
            db.commit()

            contact_captured = True
            try:
                increment_stats(db, client_id, contacts_captured=1)
            except Exception:
                pass

            # Auto-qualify once when we have reachable contact
            if (qp_email or qp_phone) and lead.status != LeadStatus.QUALIFIED:
                lead_service.update_lead_status(str(lead.lead_id), LeadStatus.QUALIFIED)
                lead_qualified = True
                try:
                    increment_stats(db, client_id, leads_qualified=1)
                except Exception:
                    pass
    
    # Email follow-up removed (feature no longer supported)
    
    db.commit()
    
    response_payload = {
        "session_id": str(session.session_id),
        "response": ai_response,
        "context_used": len(context_results) > 0,
        "lead_qualified": lead_qualified,
        "contact_captured": contact_captured,
        "tool_results": tool_results,
        "welcome_message": deployment.welcome_message if not session_id else None
    }

    # Optionally attach sources
    if return_sources:
        sources = []
        for doc in context_results:
            meta = getattr(doc, "metadata", {}) or {}
            sources.append({
                "document_id": meta.get("document_id"),
                "metadata": meta,
                "snippet": (doc.page_content or "")[:300]
            })
        response_payload["sources"] = sources

    return response_payload

# Removed old qualification function - now handled by Gemini tools

@router.get("/{custom_client_id}/history/{session_id}")
async def get_chat_history(
    custom_client_id: str,
    session_id: str,
    db: Session = Depends(get_db)
):
    """Get chat history for a session"""
    
    # Verify deployment exists
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.custom_client_id == custom_client_id,
        ClientDeployment.is_deployed == True
    ).first()
    
    if not deployment:
        raise HTTPException(status_code=404, detail="Chatbot not found")
    
    # Get session
    session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id,
        ChatSession.client_id == deployment.client_id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get chat history
    messages = db.query(ChatHistory).filter(
        ChatHistory.session_id == session_id
    ).order_by(ChatHistory.timestamp.asc()).all()
    
    return {
        "session_id": session_id,
        "messages": [
            {
                "sender": msg.sender.value,
                "message": msg.message_text,
                "timestamp": msg.timestamp
            }
            for msg in messages
        ]
    }
