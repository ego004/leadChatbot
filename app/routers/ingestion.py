from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.database import get_db
from app.models.client import Client, IngestionStatus
from app.auth import require_admin
from app.tasks.ingestion import start_ingestion_pipeline

router = APIRouter(
    prefix="/api/admin/clients",
    tags=["Ingestion"],
    dependencies=[Depends(require_admin)]
)


@router.post("/{client_id}/ingest", status_code=status.HTTP_202_ACCEPTED)
def trigger_ingestion(
    client_id: UUID,
    db: Session = Depends(get_db)
):
    """Trigger the ingestion pipeline for a client (Admin only)"""
    # Check if client exists
    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    
    # Check if ingestion is already in progress
    if client.ingestion_status == IngestionStatus.SCRAPING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ingestion already in progress"
        )
    
    try:
        # Start the ingestion pipeline
        task_id = start_ingestion_pipeline(str(client_id))
        
        # Update status to pending (will be updated to scraping by the task)
        client.ingestion_status = IngestionStatus.PENDING
        db.commit()
        
        return {
            "message": "Ingestion pipeline started",
            "task_id": task_id,
            "client_id": client_id
        }
        
    except Exception as e:
        # Set status to failed if pipeline couldn't start
        client.ingestion_status = IngestionStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start ingestion pipeline: {str(e)}"
        )
