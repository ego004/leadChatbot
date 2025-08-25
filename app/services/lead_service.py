from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import Optional, Dict, Any, List
from app.models.lead import Lead, ChatSession, ChatHistory, EmailMessage, LeadStatus
from app.models.client import Client
from app.database import get_db
import uuid


class LeadService:
    """Service for managing leads with deduplication and WhatsApp integration"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def find_or_create_lead(self, client_id: str, phone_number: Optional[str] = None, 
                           email: Optional[str] = None, name: Optional[str] = None,
                           browser_session_id: Optional[str] = None) -> Lead:
        """Find an existing lead or create new.
        Lookup order: email > phone_number > browser_session_id.
        Updates missing fields on existing lead.
        """
        # 1) Try by email
        if email:
            existing_lead = self.db.query(Lead).filter(
                and_(Lead.client_id == client_id, Lead.email == email)
            ).first()
            if existing_lead:
                if phone_number and not existing_lead.phone_number:
                    existing_lead.phone_number = phone_number
                if name and not existing_lead.name:
                    existing_lead.name = name
                if browser_session_id:
                    existing_lead.browser_session_id = browser_session_id
                self.db.commit()
                return existing_lead

        # 2) Try by phone
        if phone_number:
            existing_lead = self.db.query(Lead).filter(
                and_(Lead.client_id == client_id, Lead.phone_number == phone_number)
            ).first()
            if existing_lead:
                if email and not existing_lead.email:
                    existing_lead.email = email
                if name and not existing_lead.name:
                    existing_lead.name = name
                if browser_session_id:
                    existing_lead.browser_session_id = browser_session_id
                self.db.commit()
                return existing_lead

        # 3) Try by browser session
        if browser_session_id:
            existing_lead = self.db.query(Lead).filter(
                and_(Lead.client_id == client_id, Lead.browser_session_id == browser_session_id)
            ).first()
            if existing_lead:
                if email and not existing_lead.email:
                    existing_lead.email = email
                if phone_number and not existing_lead.phone_number:
                    existing_lead.phone_number = phone_number
                if name and not existing_lead.name:
                    existing_lead.name = name
                self.db.commit()
                return existing_lead

        # Create new
        new_lead = Lead(
            client_id=client_id,
            phone_number=phone_number,
            email=email,
            name=name,
            browser_session_id=browser_session_id,
        )
        self.db.add(new_lead)
        self.db.commit()
        self.db.refresh(new_lead)
        return new_lead

    def find_or_create_lead_with_flag(self, client_id: str, phone_number: Optional[str] = None,
                                      email: Optional[str] = None, name: Optional[str] = None,
                                      browser_session_id: Optional[str] = None) -> tuple[Lead, bool]:
        """Same as find_or_create_lead but returns a (lead, created) tuple.
        created=True if a new lead row was inserted.
        Lookup order: email > phone_number > browser_session_id.
        """
        # 1) Try by email
        if email:
            existing_lead = self.db.query(Lead).filter(
                and_(Lead.client_id == client_id, Lead.email == email)
            ).first()
            if existing_lead:
                if phone_number and not existing_lead.phone_number:
                    existing_lead.phone_number = phone_number
                if name and not existing_lead.name:
                    existing_lead.name = name
                if browser_session_id:
                    existing_lead.browser_session_id = browser_session_id
                self.db.commit()
                return existing_lead, False

        # 2) Try by phone
        if phone_number:
            existing_lead = self.db.query(Lead).filter(
                and_(Lead.client_id == client_id, Lead.phone_number == phone_number)
            ).first()
            if existing_lead:
                if email and not existing_lead.email:
                    existing_lead.email = email
                if name and not existing_lead.name:
                    existing_lead.name = name
                if browser_session_id:
                    existing_lead.browser_session_id = browser_session_id
                self.db.commit()
                return existing_lead, False

        # 3) Try by browser session
        if browser_session_id:
            existing_lead = self.db.query(Lead).filter(
                and_(Lead.client_id == client_id, Lead.browser_session_id == browser_session_id)
            ).first()
            if existing_lead:
                if email and not existing_lead.email:
                    existing_lead.email = email
                if phone_number and not existing_lead.phone_number:
                    existing_lead.phone_number = phone_number
                if name and not existing_lead.name:
                    existing_lead.name = name
                self.db.commit()
                return existing_lead, False

        # Create new
        new_lead = Lead(
            client_id=client_id,
            phone_number=phone_number,
            email=email,
            name=name,
            browser_session_id=browser_session_id,
        )
        self.db.add(new_lead)
        self.db.commit()
        self.db.refresh(new_lead)
        return new_lead, True
    
    def get_chat_history_context(self, lead_id: str, limit: int = 10) -> str:
        """Get recent chat history for email context"""
        
        # Get the most recent chat session for this lead
        recent_session = self.db.query(ChatSession).filter(
            ChatSession.lead_id == lead_id
        ).order_by(ChatSession.created_at.desc()).first()
        
        if not recent_session:
            return "No previous chat history available."
        
        # Get recent messages from the session
        messages = self.db.query(ChatHistory).filter(
            ChatHistory.session_id == recent_session.session_id
        ).order_by(ChatHistory.timestamp.desc()).limit(limit).all()
        
        if not messages:
            return "No chat messages found."
        
        # Format messages for context
        context_lines = []
        for msg in reversed(messages):  # Reverse to show chronological order
            sender = "User" if msg.sender.value == "user" else "Bot"
            context_lines.append(f"{sender}: {msg.message_text}")
        
        return "\n".join(context_lines)
    
    def create_email_message(self, lead_id: str, client_id: str, subject: str, message_text: str,
                            is_outbound: bool = True, include_context: bool = True) -> EmailMessage:
        """Create email message with chat context"""
        
        chat_context = None
        if include_context and is_outbound:
            chat_context = self.get_chat_history_context(lead_id)
        
        email_msg = EmailMessage(
            lead_id=lead_id,
            client_id=client_id,
            subject=subject,
            message_text=message_text,
            is_outbound=is_outbound,
            chat_context=chat_context
        )
        
        self.db.add(email_msg)
        self.db.commit()
        self.db.refresh(email_msg)
        
        return email_msg
    
    def update_lead_status(self, lead_id: str, status: LeadStatus) -> Optional[Lead]:
        """Update lead status"""
        lead = self.db.query(Lead).filter(Lead.lead_id == lead_id).first()
        if lead:
            lead.status = status
            self.db.commit()
            self.db.refresh(lead)
        return lead
    
    def get_leads_for_client(self, client_id: str, status: Optional[LeadStatus] = None) -> List[Lead]:
        """Get all leads for a client, optionally filtered by status"""
        query = self.db.query(Lead).filter(Lead.client_id == client_id)
        
        if status:
            query = query.filter(Lead.status == status)
        
        return query.order_by(Lead.created_at.desc()).all()
    
    def set_email_manual_override(self, lead_id: str, override: bool = True) -> Optional[Lead]:
        """Set manual override for email messages"""
        lead = self.db.query(Lead).filter(Lead.lead_id == lead_id).first()
        if lead:
            lead.email_manual_override = override
            self.db.commit()
            self.db.refresh(lead)
        return lead
    
    def get_lead_with_email_history(self, lead_id: str) -> Optional[Dict[str, Any]]:
        """Get lead with complete email message history"""
        lead = self.db.query(Lead).filter(Lead.lead_id == lead_id).first()
        if not lead:
            return None
        
        email_messages = self.db.query(EmailMessage).filter(
            EmailMessage.lead_id == lead_id
        ).order_by(EmailMessage.created_at.asc()).all()
        
        return {
            "lead": lead,
            "email_messages": email_messages,
            "chat_context": self.get_chat_history_context(lead_id)
        }
