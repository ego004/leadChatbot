from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
from app.models.automation import SequenceType

# Base and Create Schemas for SequenceStep
class SequenceStepBase(BaseModel):
    step_number: int
    template_body: str
    delay_in_hours: int

class SequenceStepCreate(SequenceStepBase):
    pass

class SequenceStep(SequenceStepBase):
    step_id: UUID

    class Config:
        orm_mode = True

# Base and Create Schemas for Sequence
class SequenceBase(BaseModel):
    name: str
    type: SequenceType
    client_id: UUID

class SequenceCreate(SequenceBase):
    steps: List[SequenceStepCreate]

class Sequence(SequenceBase):
    sequence_id: UUID
    steps: List[SequenceStep] = []

    class Config:
        orm_mode = True

class SequenceUpdate(BaseModel):
    name: Optional[str] = None
    steps: Optional[List[SequenceStepCreate]] = None
