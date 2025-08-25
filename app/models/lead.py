from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Boolean, Text, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
import enum
from app.database import Base


class LeadStatus(enum.Enum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    LOST = "lost"


class SenderType(enum.Enum):
    USER = "user"
    BOT = "bot"


class Lead(Base):
    __tablename__ = "leads"
    
    lead_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(String(36), ForeignKey("clients.client_id"), nullable=False)
    name = Column(String(255), nullable=True)  # May not be captured initially
    email = Column(String(255), nullable=True)  # May not be captured initially
    phone_number = Column(String(64), nullable=True)
    browser_session_id = Column(String(128), nullable=True)  # For tracking same visitor
    status = Column(Enum(LeadStatus), default=LeadStatus.NEW)
    email_manual_override = Column(Boolean, default=False)  # Admin can take over email automation
    last_email_sent = Column(Text, nullable=True)  # Track last email sent
    email_thread_id = Column(String(255), nullable=True)  # Email conversation thread
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    chat_sessions = relationship("ChatSession", back_populates="lead")
    client = relationship("Client", back_populates="leads")
    email_messages = relationship("EmailMessage", back_populates="lead")
    
    # Index for email deduplication
    __table_args__ = (
        Index('idx_client_email', 'client_id', 'email'),
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    
    session_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(String(36), ForeignKey("clients.client_id"), nullable=False)
    lead_id = Column(String(36), ForeignKey("leads.lead_id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    lead = relationship("Lead", back_populates="chat_sessions")
    chat_history = relationship("ChatHistory", back_populates="session")


class ChatHistory(Base):
    __tablename__ = "chat_history"
    
    message_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("chat_sessions.session_id"), nullable=False)
    sender = Column(Enum(SenderType), nullable=False)
    message_text = Column(Text, nullable=False)
    timestamp = Column(DateTime, server_default=func.now())
    
    # Relationships
    session = relationship("ChatSession", back_populates="chat_history")


class EmailMessage(Base):
    """Track email messages for follow-ups with chat history context"""
    __tablename__ = "email_messages"
    
    message_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id = Column(String(36), ForeignKey("leads.lead_id"), nullable=False)
    client_id = Column(String(36), ForeignKey("clients.client_id"), nullable=False)
    subject = Column(String(255), nullable=False)
    message_text = Column(Text, nullable=False)
    is_outbound = Column(Boolean, default=True)  # True for sent, False for received
    email_message_id = Column(String(255), nullable=True)  # Email service message ID
    status = Column(String(32), default="pending")  # pending, sent, delivered, opened, failed
    chat_context = Column(Text, nullable=True)  # Summarized chat history for context
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    lead = relationship("Lead", back_populates="email_messages")
