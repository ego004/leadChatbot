from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID

from app.database import get_db
from app.models.client import Client
from app.models.knowledge_base import ClientDeployment
from app.auth import require_admin
from app.services.vector_store_service import VectorStoreService
from app.services.supabase_storage import supabase_storage

router = APIRouter(prefix="/api/admin/deployment", tags=["Deployment"], dependencies=[Depends(require_admin)])


@router.post("/clients/{client_id}/deploy")
def deploy_client_chatbot(
    client_id: UUID,
    website_system_prompt: str,
    whatsapp_system_prompt: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Deploy chatbot for a client (make it available)"""
    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == client_id
    ).first()
    
    if not deployment:
        deployment = ClientDeployment(client_id=client_id)
        db.add(deployment)
    
    # Update deployment settings
    deployment.is_deployed = True
    deployment.website_system_prompt = website_system_prompt
    deployment.whatsapp_system_prompt = whatsapp_system_prompt or website_system_prompt
    deployment.deployment_url = f"https://your-domain.com/widget/{client_id}"
    
    db.commit()
    
    return {
        "message": "Chatbot deployed successfully",
        "deployment_url": deployment.deployment_url,
        "widget_embed_code": f'<script src="https://your-domain.com/widget.js" data-client-id="{client_id}"></script>'
    }


@router.post("/clients/{client_id}/undeploy")
def undeploy_client_chatbot(
    client_id: UUID,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Undeploy chatbot for a client (make it unavailable)"""
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == client_id
    ).first()
    
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    deployment.is_deployed = False
    db.commit()
    
    return {"message": "Chatbot undeployed successfully"}


@router.put("/clients/{client_id}/system-prompts")
def update_system_prompts(
    client_id: UUID,
    website_system_prompt: Optional[str] = None,
    whatsapp_system_prompt: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Update system prompts for a deployed client"""
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == client_id
    ).first()
    
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    if website_system_prompt is not None:
        deployment.website_system_prompt = website_system_prompt
    
    if whatsapp_system_prompt is not None:
        deployment.whatsapp_system_prompt = whatsapp_system_prompt
    
    db.commit()
    
    return {"message": "System prompts updated successfully"}


@router.post("/clients/{client_id}/rebuild-knowledge-base")
def rebuild_knowledge_base(
    client_id: UUID,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Rebuild vector database from current knowledge documents"""
    from app.models.knowledge_base import KnowledgeDocument

    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Get all active documents
    documents = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.client_id == str(client_id),
        KnowledgeDocument.is_active == True
    ).all()

    if not documents:
        raise HTTPException(status_code=400, detail="No active documents found")

    # Initialize per-client collection and clear it
    collection = f"client_{client_id}"
    vector_store = VectorStoreService(collection_name=collection)
    vector_store.delete_collection()

    # Re-add all document contents (prefer Supabase blobs; fallback to legacy DB content)
    added = 0
    for doc in documents:
        content: Optional[str] = None
        try:
            filename = f"{doc.document_id}.md"
            content = supabase_storage.download_markdown(str(doc.client_id), filename)
        except Exception:
            content = None
        if not content:
            content = doc.content
        if not content:
            continue
        vector_store.add_text(content, metadata={"document_id": str(doc.document_id)})
        added += 1

    return {
        "message": "Knowledge base rebuilt successfully",
        "documents_processed": len(documents),
        "documents_indexed": added
    }
