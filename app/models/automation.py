from sqlalchemy import Column, String, Integer, DateTime, Enum, ForeignKey, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
import enum
from app.database import Base


class SequenceType(enum.Enum):
    EMAIL = "email"


class SequenceStatus(enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class Sequence(Base):
    __tablename__ = "sequences"
    
    sequence_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column(String(36), ForeignKey("clients.client_id"), nullable=False)
    name = Column(String(255), nullable=False)
    type = Column(Enum(SequenceType), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    steps = relationship("SequenceStep", back_populates="sequence")
    lead_states = relationship("LeadSequenceState", back_populates="sequence")


class SequenceStep(Base):
    __tablename__ = "sequence_steps"
    
    step_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sequence_id = Column(String(36), ForeignKey("sequences.sequence_id"), nullable=False)
    step_number = Column(Integer, nullable=False)
    delay_in_hours = Column(Integer, nullable=False)
    template_body = Column(Text, nullable=False)
    
    # Relationships
    sequence = relationship("Sequence", back_populates="steps")


class LeadSequenceState(Base):
    __tablename__ = "lead_sequence_states"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lead_id = Column(String(36), ForeignKey("leads.lead_id"), nullable=False)
    sequence_id = Column(String(36), ForeignKey("sequences.sequence_id"), nullable=False)
    current_step_id = Column(String(36), ForeignKey("sequence_steps.step_id"), nullable=True)
    status = Column(Enum(SequenceStatus), default=SequenceStatus.ACTIVE)
    next_send_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    sequence = relationship("Sequence", back_populates="lead_states")
    current_step = relationship("SequenceStep")
