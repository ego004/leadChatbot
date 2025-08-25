from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.database import get_db
from app.models.client import Client
from app.schemas.client import ClientCreate, ClientUpdate, ClientResponse
from app.auth import require_admin

router = APIRouter(
    prefix="/api/admin/clients",
    tags=["Clients"],
    dependencies=[Depends(require_admin)]
)


@router.post("/", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client(
    client_data: ClientCreate,
    db: Session = Depends(get_db)
):
    """Create a new client (Admin only)"""
    db_client = Client(
        name=client_data.name,
        website_url=client_data.website_url
    )
    db.add(db_client)
    db.commit()
    db.refresh(db_client)
    return db_client


@router.get("/", response_model=List[ClientResponse])
def list_clients(
    db: Session = Depends(get_db)
):
    """List all clients (Admin only)"""
    clients = db.query(Client).all()
    return clients


@router.get("/{client_id}", response_model=ClientResponse)
def get_client(
    client_id: UUID,
    db: Session = Depends(get_db)
):
    """Get details for a single client (Admin only)"""
    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    return client


@router.put("/{client_id}", response_model=ClientResponse)
def update_client(
    client_id: UUID,
    client_data: ClientUpdate,
    db: Session = Depends(get_db)
):
    """Update client details (Admin only)"""
    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found"
        )
    
    update_data = client_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(client, field, value)
    
    db.commit()
    db.refresh(client)
    return client
