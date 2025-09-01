from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from typing import Optional, List

from app.database import get_db
from app.models.form_contact import FormContact
from app.auth import require_admin

router = APIRouter(prefix="/api/form", tags=["form"])


@router.post("/contact", status_code=status.HTTP_201_CREATED)
async def submit_contact(
    request: Request,
    name: Optional[str] = None,
    email: Optional[str] = None,
    company: Optional[str] = None,
    phone: Optional[str] = None,
    service: Optional[str] = None,
    message: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Accepts contact form submissions and stores them in the formContacts table.

    Accepts values as query params, JSON body, or form-encoded body.
    """
    # If required fields not provided as query params, try JSON then form
    if not name or not email or not message:
        # Try JSON body
        try:
            data = await request.json()
            if isinstance(data, dict):
                name = name or data.get("name")
                email = email or data.get("email")
                company = company or data.get("company")
                phone = phone or data.get("phone")
                service = service or data.get("service")
                message = message or data.get("message")
        except Exception:
            pass
        # Try form body
        if not name or not email or not message:
            try:
                form = await request.form()
                name = name or form.get("name")
                email = email or form.get("email")
                company = company or form.get("company")
                phone = phone or form.get("phone")
                service = service or form.get("service")
                message = message or form.get("message")
            except Exception:
                pass

    # Basic validation
    if not name or not email or not message:
        raise HTTPException(status_code=422, detail="Fields 'name', 'email', and 'message' are required")

    record = FormContact(
        name=name.strip(),
        email=email.strip(),
        company=(company or None),
        phone=(phone or None),
        service=(service or None),
        message=message.strip(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "id": record.id,
        "created_at": record.created_at,
        "status": "stored",
    }


@router.get("/contacts")
def get_all_contact_form_entries(
    db: Session = Depends(get_db),
    _: dict = Depends(require_admin)
):
    """Retrieve all contact form submissions. Admin access required."""
    contacts = db.query(FormContact).order_by(FormContact.created_at.desc()).all()
    
    return {
        "total_count": len(contacts),
        "contacts": [
            {
                "id": contact.id,
                "name": contact.name,
                "email": contact.email,
                "company": contact.company,
                "phone": contact.phone,
                "service": contact.service,
                "message": contact.message,
                "created_at": contact.created_at
            } for contact in contacts
        ]
    }
