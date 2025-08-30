from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.sql import func
import uuid

from app.database import Base


class FormContact(Base):
    __tablename__ = "formContacts"  # requested table name

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    email = Column(String(320), nullable=False)
    company = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    service = Column(String(100), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
