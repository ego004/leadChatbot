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
    ingestion_status = Column(Enum(IngestionStatus), default=IngestionStatus.PENDING)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    knowledge_documents = relationship("KnowledgeDocument", back_populates="client")
    deployment = relationship("ClientDeployment", back_populates="client", uselist=False)
    leads = relationship("Lead", back_populates="client")

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
