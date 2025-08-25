from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from app.database import get_db
from app.models.client import Client, IngestionStatus
from app.models.knowledge_base import KnowledgeDocument, ClientDeployment
from app.models.lead import Lead
from app.auth import require_admin
from app.services.ingestion_service import IngestionService
from app.services.supabase_storage import supabase_storage

router = APIRouter(prefix="/admin", tags=["admin"])
ingestion_service = IngestionService()


# ============ CLIENT MANAGEMENT ============

@router.post("/clients", status_code=status.HTTP_201_CREATED)
def create_client(
    name: str,
    website_url: str,
    contact_email: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Create a new client"""
    client = Client(
        name=name,
        website_url=website_url,
        contact_email=contact_email
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    
    # Create deployment record
    deployment = ClientDeployment(client_id=client.client_id)
    db.add(deployment)
    db.commit()
    
    return {"client_id": client.client_id, "name": client.name, "status": "created"}


@router.get("/clients")
def list_all_clients(
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """List all clients with their deployment status"""
    clients = db.query(Client).all()
    result = []
    
    for client in clients:
        deployment = db.query(ClientDeployment).filter(
            ClientDeployment.client_id == client.client_id
        ).first()
        
        lead_count = db.query(Lead).filter(Lead.client_id == client.client_id).count()
        
        result.append({
            "client_id": client.client_id,
            "name": client.name,
            "website_url": client.website_url,
            "contact_email": client.contact_email,
            "ingestion_status": client.ingestion_status.value,
            "is_deployed": deployment.is_deployed if deployment else False,
            "lead_count": lead_count,
            "created_at": client.created_at
        })
    
    return result


@router.get("/clients/{client_id}")
def get_client_details(
    client_id: UUID,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Get detailed client information"""
    client = db.query(Client).filter(Client.client_id == str(client_id)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == str(client_id)
    ).first()
    
    documents = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.client_id == str(client_id)
    ).all()
    
    leads = db.query(Lead).filter(Lead.client_id == str(client_id)).all()
    
    return {
        "client": {
            "client_id": client.client_id,
            "name": client.name,
            "website_url": client.website_url,
            "contact_email": client.contact_email,
            "ingestion_status": client.ingestion_status.value,
            "created_at": client.created_at
        },
        "deployment": {
            "is_deployed": deployment.is_deployed if deployment else False,
            "website_system_prompt": deployment.website_system_prompt if deployment else None,
            "deployment_url": deployment.deployment_url if deployment else None
        },
        "knowledge_base": [
            {
                "document_id": doc.document_id,
                "title": doc.title,
                "source_url": doc.source_url,
                "is_active": doc.is_active,
                "updated_at": doc.updated_at
            } for doc in documents
        ],
        "leads": [
            {
                "lead_id": lead.lead_id,
                "name": lead.name,
                "email": lead.email,
                "phone_number": lead.phone_number,
                "status": lead.status.value,
                "email_manual_override": lead.email_manual_override,
                "created_at": lead.created_at
            } for lead in leads
        ]
    }


@router.delete("/clients/{client_id}")
def delete_client(
    client_id: UUID,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Delete a client and all associated data"""
    client = db.query(Client).filter(Client.client_id == str(client_id)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Delete all related data (cascade should handle this, but being explicit)
    db.query(KnowledgeDocument).filter(KnowledgeDocument.client_id == str(client_id)).delete()
    db.query(ClientDeployment).filter(ClientDeployment.client_id == str(client_id)).delete()
    db.query(Lead).filter(Lead.client_id == str(client_id)).delete()
    
    # Delete vector collection for the client
    try:
        ingestion_service.rebuild_vectors_for_client(db, str(client_id))  # this deletes and rebuilds; we'll just delete
    except Exception:
        pass
    # Explicit delete collection without rebuild
    try:
        from app.services.vector_store_service import VectorStoreService
        VectorStoreService(collection_name=f"client_{client_id}").delete_collection()
    except Exception:
        pass

    db.delete(client)
    db.commit()
    
    return {"message": "Client deleted successfully"}


# ============ KNOWLEDGE BASE MANAGEMENT ============

@router.post("/clients/{client_id}/scrape")
async def trigger_website_scraping(
    client_id: UUID,
    user_prompt: str | None = None,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Trigger website scraping for a client"""
    client = db.query(Client).filter(Client.client_id == str(client_id)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    if client.ingestion_status == IngestionStatus.SCRAPING:
        raise HTTPException(status_code=409, detail="Scraping already in progress")
    
    # Run ingestion pipeline (crawl -> llm filter -> store -> vectors)
    result = await ingestion_service.ingest_client_website(
        db=db,
        client_id=str(client_id),
        website_url=client.website_url,
        user_prompt=user_prompt,
    )
    return result


@router.get("/clients/{client_id}/documents")
def list_knowledge_documents(
    client_id: UUID,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """List all knowledge documents for a client"""
    documents = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.client_id == str(client_id)
    ).all()
    
    return [
        {
            "document_id": doc.document_id,
            "title": doc.title,
            "source_url": doc.source_url,
            "is_active": doc.is_active,
            "content_preview": doc.content[:200] + "..." if len(doc.content) > 200 else doc.content,
            "updated_at": doc.updated_at
        } for doc in documents
    ]


@router.get("/clients/{client_id}/documents/{document_id}")
def get_document_content(
    client_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Get full content of a knowledge document"""
    document = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.document_id == document_id,
        KnowledgeDocument.client_id == str(client_id)
    ).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return {
        "document_id": document.document_id,
        "title": document.title,
        "content": document.content,
        "source_url": document.source_url,
        "is_active": document.is_active,
        "created_at": document.created_at,
        "updated_at": document.updated_at
    }


@router.put("/clients/{client_id}/documents/{document_id}")
def update_document_content(
    client_id: UUID,
    document_id: UUID,
    title: Optional[str] = None,
    content: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Update knowledge document content"""
    document = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.document_id == document_id,
        KnowledgeDocument.client_id == str(client_id)
    ).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if title is not None:
        document.title = title
    if content is not None:
        document.content = content
    if is_active is not None:
        document.is_active = is_active
    
    db.commit()
    # Rebuild vectors to reflect changes
    ingestion_service.rebuild_vectors_for_client(db, str(client_id))
    
    return {"message": "Document updated successfully"}


@router.post("/clients/{client_id}/documents")
def create_new_document(
    client_id: UUID,
    title: str,
    content: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Create a new knowledge document"""
    client = db.query(Client).filter(Client.client_id == str(client_id)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    document = KnowledgeDocument(
        client_id=str(client_id),
        title=title,
        content=content
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    # Rebuild vectors to include new doc
    ingestion_service.rebuild_vectors_for_client(db, str(client_id))
    
    return {"document_id": document.document_id, "message": "Document created successfully"}


@router.delete("/clients/{client_id}/documents/{document_id}")
def delete_document(
    client_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Delete a knowledge document"""
    document = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.document_id == document_id,
        KnowledgeDocument.client_id == str(client_id)
    ).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Best-effort: delete mirrored markdown from storage before DB delete
    try:
        supabase_storage.delete_markdown(str(client_id), f"{document_id}.md")
    except Exception:
        pass

    db.delete(document)
    db.commit()
    # Rebuild vectors to remove deleted doc
    ingestion_service.rebuild_vectors_for_client(db, str(client_id))
    
    return {"message": "Document deleted successfully"}


# ============ CLIENT UPDATE ============

@router.put("/clients/{client_id}")
def update_client(
    client_id: UUID,
    name: Optional[str] = None,
    website_url: Optional[str] = None,
    contact_email: Optional[str] = None,
    # Per-client email settings
    smtp_server: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
    smtp_from_name: Optional[str] = None,
    imap_server: Optional[str] = None,
    imap_port: Optional[int] = None,
    email_enabled: Optional[bool] = None,
    rebuild_vectors: bool = False,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    if name is not None:
        client.name = name
    if website_url is not None:
        client.website_url = website_url
    if contact_email is not None:
        client.contact_email = contact_email
    # Apply email settings if provided
    if smtp_server is not None:
        client.smtp_server = smtp_server
    if smtp_port is not None:
        client.smtp_port = smtp_port
    if smtp_user is not None:
        client.smtp_user = smtp_user
    if smtp_password is not None:
        client.smtp_password = smtp_password
    if smtp_from_name is not None:
        client.smtp_from_name = smtp_from_name
    if imap_server is not None:
        client.imap_server = imap_server
    if imap_port is not None:
        client.imap_port = imap_port
    if email_enabled is not None:
        client.email_enabled = email_enabled
    db.commit()
    if rebuild_vectors:
        ingestion_service.rebuild_vectors_for_client(db, str(client_id))
    return {"message": "Client updated"}
