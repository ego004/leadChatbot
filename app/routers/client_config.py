from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models.knowledge_base import ClientDeployment
from app.models.client import Client
import secrets
import string
from fastapi import Body
from app.auth import require_admin

router = APIRouter(prefix="/api/admin/client-config", tags=["Client Configuration"], dependencies=[Depends(require_admin)])


@router.get("/client/{client_id}/deployment")
async def get_client_deployment(client_id: str, db: Session = Depends(get_db)):
    """Get client deployment configuration"""
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == client_id
    ).first()
    
    if not deployment:
        # Create default deployment config
        deployment = ClientDeployment(
            client_id=client_id,
            is_deployed=False,
            website_system_prompt="You are a helpful AI assistant for our company. Help visitors with their questions and identify potential leads.",
            welcome_message="Hello! How can I help you today?",
            email_system_prompt="You are a helpful AI sales assistant replying to emails. Be professional, concise, and move the conversation forward.",
            email_welcome_message="Thanks for reaching out! I'd be happy to help."
        )
        db.add(deployment)
        db.commit()
        db.refresh(deployment)
    
    return {"deployment": deployment}


@router.put("/client/{client_id}/system-prompts")
async def update_system_prompts(
    client_id: str,
    website_system_prompt: Optional[str] = None,
    welcome_message: Optional[str] = None,
    email_system_prompt: Optional[str] = None,
    email_welcome_message: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Update client system prompts and welcome message"""
    
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == client_id
    ).first()
    
    if not deployment:
        deployment = ClientDeployment(client_id=client_id)
        db.add(deployment)
    
    # Update fields if provided
    if website_system_prompt is not None:
        deployment.website_system_prompt = website_system_prompt
    if welcome_message is not None:
        deployment.welcome_message = welcome_message
    if email_system_prompt is not None:
        deployment.email_system_prompt = email_system_prompt
    if email_welcome_message is not None:
        deployment.email_welcome_message = email_welcome_message
    
    db.commit()
    db.refresh(deployment)
    
    return {
        "success": True,
        "message": "System prompts updated successfully",
        "deployment": deployment
    }


@router.post("/client/{client_id}/generate-custom-id")
async def generate_custom_client_id(client_id: str, db: Session = Depends(get_db)):
    """Generate unique custom client ID for deployment"""
    
    # Get client info for generating meaningful ID
    client = db.query(Client).filter(Client.client_id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    
    # Generate custom ID based on company name + random string
    company_part = "".join(c.lower() for c in client.name if c.isalnum())[:8]
    random_part = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
    custom_id = f"{company_part}-{random_part}"
    
    # Ensure uniqueness
    while db.query(ClientDeployment).filter(ClientDeployment.custom_client_id == custom_id).first():
        random_part = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
        custom_id = f"{company_part}-{random_part}"
    
    # Update deployment
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == client_id
    ).first()
    
    if not deployment:
        deployment = ClientDeployment(client_id=client_id)
        db.add(deployment)
    
    deployment.custom_client_id = custom_id
    db.commit()
    db.refresh(deployment)
    
    return {
        "success": True,
        "custom_client_id": custom_id,
        "message": "Custom client ID generated successfully"
    }


@router.post("/client/{client_id}/deploy")
async def deploy_chatbot(client_id: str, db: Session = Depends(get_db)):
    """Deploy chatbot for client"""
    
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == client_id
    ).first()
    
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment configuration not found")
    
    if not deployment.custom_client_id:
        raise HTTPException(status_code=400, detail="Custom client ID not generated")
    
    # Generate deployment URL
    base_url = "https://your-domain.com"  # Replace with actual domain
    deployment_url = f"{base_url}/chat/{deployment.custom_client_id}"
    
    # Update deployment status
    deployment.is_deployed = True
    deployment.deployment_url = deployment_url
    
    db.commit()
    db.refresh(deployment)
    
    return {
        "success": True,
        "message": "Chatbot deployed successfully",
        "deployment_url": deployment_url,
        "custom_client_id": deployment.custom_client_id,
        "embed_code": f'<iframe src="{deployment_url}" width="400" height="600" frameborder="0"></iframe>'
    }


@router.post("/client/{client_id}/undeploy")
async def undeploy_chatbot(client_id: str, db: Session = Depends(get_db)):
    """Undeploy chatbot for client"""
    
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == client_id
    ).first()
    
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment configuration not found")
    
    deployment.is_deployed = False
    deployment.deployment_url = None
    
    db.commit()
    db.refresh(deployment)
    
    return {
        "success": True,
        "message": "Chatbot undeployed successfully"
    }


@router.post("/client/{client_id}/generate-token")
async def generate_deployment_token(client_id: str, db: Session = Depends(get_db)):
    """Generate and store a new deployment API token for the client's chatbot."""
    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == client_id
    ).first()
    if not deployment:
        deployment = ClientDeployment(client_id=client_id)
        db.add(deployment)

    # Generate secure token
    token = secrets.token_urlsafe(32)
    deployment.deployment_api_token = token
    db.commit()
    db.refresh(deployment)

    return {
        "success": True,
        "deployment_api_token": token
    }


@router.put("/client/{client_id}/token")
async def set_deployment_token(
    client_id: str,
    token: str = Body(..., embed=True),
    db: Session = Depends(get_db)
):
    """Set a specific deployment API token for the client's chatbot."""
    if not token or len(token) < 12:
        raise HTTPException(status_code=400, detail="Token must be at least 12 characters")

    deployment = db.query(ClientDeployment).filter(
        ClientDeployment.client_id == client_id
    ).first()
    if not deployment:
        deployment = ClientDeployment(client_id=client_id)
        db.add(deployment)

    deployment.deployment_api_token = token
    db.commit()
    db.refresh(deployment)

    return {
        "success": True,
        "message": "Deployment token set successfully"
    }
