from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app import database
from app.models import automation as models
from app.schemas import automation as schemas
from app.auth import require_admin

router = APIRouter(
    prefix="/api/admin/automations",
    tags=["Automations"],
    dependencies=[Depends(require_admin)]
)

@router.post("/sequences/", response_model=schemas.Sequence)
def create_sequence(sequence: schemas.SequenceCreate, db: Session = Depends(database.get_db)):
    db_sequence = models.Sequence(
        name=sequence.name,
        type=sequence.type,
        client_id=sequence.client_id
    )
    db.add(db_sequence)
    db.commit()
    db.refresh(db_sequence)

    for step_data in sequence.steps:
        db_step = models.SequenceStep(
            sequence_id=db_sequence.sequence_id,
            **step_data.dict()
        )
        db.add(db_step)
    
    db.commit()
    db.refresh(db_sequence)
    return db_sequence

@router.get("/sequences/client/{client_id}", response_model=List[schemas.Sequence])
def get_sequences_for_client(client_id: UUID, db: Session = Depends(database.get_db)):
    sequences = db.query(models.Sequence).filter(models.Sequence.client_id == client_id).all()
    return sequences

@router.get("/sequences/{sequence_id}", response_model=schemas.Sequence)
def get_sequence(sequence_id: UUID, db: Session = Depends(database.get_db)):
    db_sequence = db.query(models.Sequence).filter(models.Sequence.sequence_id == sequence_id).first()
    if not db_sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")
    return db_sequence

@router.put("/sequences/{sequence_id}", response_model=schemas.Sequence)
def update_sequence(sequence_id: UUID, sequence: schemas.SequenceUpdate, db: Session = Depends(database.get_db)):
    db_sequence = db.query(models.Sequence).filter(models.Sequence.sequence_id == sequence_id).first()
    if not db_sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")

    if sequence.name:
        db_sequence.name = sequence.name

    if sequence.steps is not None:
        # Delete old steps
        db.query(models.SequenceStep).filter(models.SequenceStep.sequence_id == sequence_id).delete()
        # Add new steps
        for step_data in sequence.steps:
            db_step = models.SequenceStep(
                sequence_id=sequence_id,
                **step_data.dict()
            )
            db.add(db_step)
    
    db.commit()
    db.refresh(db_sequence)
    return db_sequence

@router.delete("/sequences/{sequence_id}", status_code=204)
def delete_sequence(sequence_id: UUID, db: Session = Depends(database.get_db)):
    db_sequence = db.query(models.Sequence).filter(models.Sequence.sequence_id == sequence_id).first()
    if not db_sequence:
        raise HTTPException(status_code=404, detail="Sequence not found")
    
    # Also deletes associated steps due to cascade
    db.delete(db_sequence)
    db.commit()
    return
