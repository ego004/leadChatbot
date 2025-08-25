from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database import Base


class KnowledgeDocument(Base):
    """Individual markdown documents that make up a client's knowledge base"""
    __tablename__ = "knowledge_documents"
    
    document_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(String(36), ForeignKey("clients.client_id"), nullable=False)
    title = Column(String(255), nullable=False)
    # Full markdown will be stored in Supabase Storage; DB holds preview + path
    content = Column(Text, nullable=True)  # Deprecated: kept nullable for backward compatibility
    content_preview = Column(Text, nullable=True)
    storage_path = Column(String(512), nullable=True)  # e.g., "{client_id}/{document_id}.md"
    source_url = Column(String(2048), nullable=True)  # Original URL if scraped
    is_active = Column(Boolean, default=True)  # Can be disabled without deletion
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    client = relationship("Client", back_populates="knowledge_documents")


class ClientDeployment(Base):
    """Track which clients have active chatbot deployments"""
    __tablename__ = "client_deployments"
    
    deployment_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(String(36), ForeignKey("clients.client_id"), nullable=False)
    is_deployed = Column(Boolean, default=False)
    website_system_prompt = Column(Text, nullable=True)
    welcome_message = Column(Text, nullable=True)
    # Email-specific prompts
    email_system_prompt = Column(Text, nullable=True)
    email_welcome_message = Column(Text, nullable=True)
    deployment_url = Column(String(2048), nullable=True)  # Widget embed URL
    custom_client_id = Column(String(128), nullable=True, unique=True)  # Custom ID for deployment
    # Optional per-client chat API token
    deployment_api_token = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    client = relationship("Client", back_populates="deployment")
