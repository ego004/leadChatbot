from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from app.database import get_db
from app.models.client import Client, IngestionStatus
from app.auth import require_admin
from app.tasks.ingestion import run_ingestion_pipeline_sync

router = APIRouter(
    prefix="/api/admin/clients",
    tags=["Ingestion"],
    dependencies=[Depends(require_admin)]
)


@router.post("/{client_id}/ingest", status_code=status.HTTP_200_OK)
def trigger_ingestion(
    client_id: UUID,
    db: Session = Depends(get_db)
):
    """Trigger the ingestion pipeline for a client (Admin only)"""
    # Check if client exists (model stores client_id as string)
    client = db.query(Client).filter(Client.client_id == str(client_id)).first()
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
        # Run the ingestion pipeline synchronously (no Celery)
        result = run_ingestion_pipeline_sync(str(client_id))
        return {"message": "Ingestion completed", **result}
    except Exception as e:
        # Set status to failed if pipeline couldn't complete
        client = db.query(Client).filter(Client.client_id == str(client_id)).first()
        if client:
            client.ingestion_status = IngestionStatus.FAILED
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {str(e)}"
        )
