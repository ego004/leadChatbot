from sqlalchemy import Column, String, Text, DateTime, Enum, Integer, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, synonym
import uuid
import enum
from app.database import Base


class IngestionStatus(enum.Enum):
    PENDING = "pending"
    SCRAPING = "scraping"
    COMPLETED = "completed"
    FAILED = "failed"


class Client(Base):
    __tablename__ = "clients"
    
    client_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    website_url = Column(String(2048), nullable=False)
    contact_email = Column(String(255), nullable=True)  # Client's contact info
    # Backwards-compatible alias used by tests and older code
    email = synonym('contact_email')
    ingestion_status = Column(Enum(IngestionStatus), default=IngestionStatus.PENDING)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Per-client Email (SMTP/IMAP) configuration
    smtp_server = Column(String(255), nullable=True)
    smtp_port = Column(Integer, nullable=True)
    smtp_user = Column(String(255), nullable=True)
    smtp_password = Column(String(255), nullable=True)
    smtp_from_name = Column(String(255), nullable=True)
    imap_server = Column(String(255), nullable=True)
    imap_port = Column(Integer, nullable=True)
    email_enabled = Column(Boolean, nullable=True, default=None)  # None -> use global default
    
    # Relationships
    knowledge_documents = relationship("KnowledgeDocument", back_populates="client")
    deployment = relationship("ClientDeployment", back_populates="client", uselist=False)
    leads = relationship("Lead", back_populates="client")

    # Accept both 'email' and 'contact_email' in constructor
    def __init__(self, **kwargs):
        if 'email' in kwargs and 'contact_email' not in kwargs:
            kwargs['contact_email'] = kwargs.pop('email')
        for k, v in kwargs.items():
            setattr(self, k, v)
