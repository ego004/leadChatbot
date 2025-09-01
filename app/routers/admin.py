from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from app.database import get_db
from app.models.client import Client, IngestionStatus
from app.models.knowledge_base import KnowledgeDocument, ClientDeployment
from app.models.lead import Lead
from app.models.client_user import ClientUser
from app.auth import require_admin
from app.services.ingestion_service import IngestionService
from passlib.hash import bcrypt

router = APIRouter(prefix="/admin", tags=["admin"])
ingestion_service = IngestionService()


# ============ CLIENT MANAGEMENT ============

@router.post("/clients", status_code=status.HTTP_201_CREATED)
async def create_client(
    request: Request,
    name: Optional[str] = None,
    website_url: Optional[str] = None,
    contact_email: Optional[str] = None,
    # Optional deployment fields
    is_deployed: Optional[bool] = None,
    custom_client_id: Optional[str] = None,
    deployment_url: Optional[str] = None,
    deployment_api_token: Optional[str] = None,
    website_system_prompt: Optional[str] = None,
    welcome_message: Optional[str] = None,
    email_welcome_message: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Create a new client.

    Accepts values via query params, form fields, or JSON body
    (name, website_url, optional contact_email).
    """
    # If required fields not provided as query params, try JSON then form
    if not name or not website_url:
        # Try JSON
        try:
            data = await request.json()
            if isinstance(data, dict):
                name = name or data.get("name")
                website_url = website_url or data.get("website_url")
                contact_email = contact_email or data.get("contact_email")
        except Exception:
            pass
        # Try form
        if not name or not website_url:
            try:
                form = await request.form()
                name = name or form.get("name")
                website_url = website_url or form.get("website_url")
                contact_email = contact_email or form.get("contact_email")
                # Deployment fields
                if is_deployed is None:
                    try:
                        is_deployed = form.get("is_deployed")
                        if isinstance(is_deployed, str):
                            is_deployed = is_deployed.lower() in ["1","true","yes","on"]
                    except Exception:
                        is_deployed = None
                custom_client_id = custom_client_id or form.get("custom_client_id")
                deployment_url = deployment_url or form.get("deployment_url")
                deployment_api_token = deployment_api_token or form.get("deployment_api_token")
                website_system_prompt = website_system_prompt or form.get("website_system_prompt")
                welcome_message = welcome_message or form.get("welcome_message")
                email_welcome_message = email_welcome_message or form.get("email_welcome_message")
            except Exception:
                pass

    if not name or not website_url:
        raise HTTPException(status_code=422, detail="Fields 'name' and 'website_url' are required")

    client = Client(
        name=name,
        website_url=website_url,
        contact_email=contact_email
    )
    db.add(client)
    db.commit()
    db.refresh(client)

    # Create deployment record (populate optional fields if provided)
    deployment = ClientDeployment(
        client_id=client.client_id,
        is_deployed=bool(is_deployed) if is_deployed is not None else False,
        custom_client_id=custom_client_id,
        deployment_url=deployment_url,
        deployment_api_token=deployment_api_token,
        website_system_prompt=website_system_prompt,
        welcome_message=welcome_message,
        email_welcome_message=email_welcome_message,
    )
    db.add(deployment)
    db.commit()

    return {"client_id": client.client_id, "name": client.name, "status": "created"}


@router.put("/clients/{client_id}/deployment")
def update_client_deployment(
    client_id: UUID,
    is_deployed: Optional[bool] = None,
    custom_client_id: Optional[str] = None,
    deployment_url: Optional[str] = None,
    deployment_api_token: Optional[str] = None,
    website_system_prompt: Optional[str] = None,
    welcome_message: Optional[str] = None,
    email_welcome_message: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Update deployment settings for a client."""
    client = db.query(Client).filter(Client.client_id == str(client_id)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    deployment = db.query(ClientDeployment).filter(ClientDeployment.client_id == str(client_id)).first()
    if not deployment:
        deployment = ClientDeployment(client_id=str(client_id))
        db.add(deployment)
        db.commit()
        db.refresh(deployment)

    if is_deployed is not None:
        deployment.is_deployed = is_deployed
    if custom_client_id is not None and custom_client_id.strip():
        deployment.custom_client_id = custom_client_id.strip()
    if deployment_url is not None:
        deployment.deployment_url = deployment_url
    if deployment_api_token is not None:
        deployment.deployment_api_token = deployment_api_token
    if website_system_prompt is not None:
        deployment.website_system_prompt = website_system_prompt
    if welcome_message is not None:
        deployment.welcome_message = welcome_message
    if email_welcome_message is not None:
        deployment.email_welcome_message = email_welcome_message
    db.commit()
    db.refresh(deployment)
    return {"message": "Deployment updated", "deployment": {
        "client_id": str(deployment.client_id),
        "is_deployed": deployment.is_deployed,
        "custom_client_id": deployment.custom_client_id,
        "deployment_url": deployment.deployment_url,
        "deployment_api_token": deployment.deployment_api_token,
        "website_system_prompt": deployment.website_system_prompt,
        "welcome_message": deployment.welcome_message,
        "email_welcome_message": deployment.email_welcome_message,
    }}


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
        from app.services.service_manager import service_manager
        service_manager.get_vector_store_service(f"client_{client_id}").delete_collection()
    except Exception:
        pass

    db.delete(client)
    db.commit()
    
    return {"message": "Client deleted successfully"}




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


# ============ CLIENT USERS (DASHBOARD CREDENTIALS) ============

@router.post("/clients/{client_id}/users", status_code=status.HTTP_201_CREATED)
async def create_client_user(
    client_id: UUID,
    request: Request,
    email: Optional[str] = None,
    password: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Create a dashboard user for a client (email/password).

    Accepts values via query params, form fields, or JSON body.
    """
    # If required fields not provided as query params, try JSON then form
    if not email or not password:
        try:
            data = await request.json()
            if isinstance(data, dict):
                email = email or data.get("email")
                password = password or data.get("password")
        except Exception:
            pass
        if not email or not password:
            try:
                form = await request.form()
                email = email or form.get("email")
                password = password or form.get("password")
            except Exception:
                pass

    if not email or not password:
        raise HTTPException(status_code=422, detail="Fields 'email' and 'password' are required")

    client = db.query(Client).filter(Client.client_id == str(client_id)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    existing = db.query(ClientUser).filter(
        ClientUser.client_id == str(client_id),
        ClientUser.email == email
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists for this client")
    user = ClientUser(
        client_id=str(client_id),
        email=email,
        password_hash=bcrypt.hash(password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user_id": user.user_id, "client_id": user.client_id, "email": user.email}


@router.post("/clients/{client_id}/users/{user_id}/reset-password")
def reset_client_user_password(
    client_id: UUID,
    user_id: UUID,
    new_password: str,
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Reset a client user's password."""
    user = db.query(ClientUser).filter(
        ClientUser.user_id == str(user_id),
        ClientUser.client_id == str(client_id)
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = bcrypt.hash(new_password)
    db.commit()
    return {"message": "Password reset successfully"}
