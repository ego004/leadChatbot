from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body, Request, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models.knowledge_base import KnowledgeDocument
from app.services.crawler import crawl_website, read_and_combine_markdown_files, cleanup_temp_files
from app.services.service_manager import service_manager
from app.services.supabase_storage import supabase_storage
from app.auth import require_admin
import os
import tempfile
import uuid
from pathlib import Path
import logging

router = APIRouter(prefix="/api/admin/knowledge-base", tags=["Knowledge Base Management"], dependencies=[Depends(require_admin)])
logger = logging.getLogger(__name__)

class AddMarkdownRequest(BaseModel):
    title: str
    content: str


@router.get("/client/{client_id}")
async def get_client_knowledge_base(client_id: str, db: Session = Depends(get_db)):
    """Get all knowledge base entries for a client"""
    kb_entries = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.client_id == client_id
    ).order_by(KnowledgeDocument.created_at.desc()).all()
    
    return {"knowledge_base": kb_entries}


@router.post("/client/{client_id}/add-markdown")
async def add_markdown_content(
    client_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """Add new markdown content to client's knowledge base via JSON keys 'title' and 'content'."""
    
    # Accept JSON payload or form fields explicitly (avoid Body-model ambiguity)
    req_title = None
    req_content = None
    try:
        ctype = request.headers.get("content-type", "?")
        logger.debug(f"[KB] add-markdown: content-type={ctype}")
    except Exception:
        pass
    # Try JSON first
    try:
        data = await request.json()
        if isinstance(data, dict):
            req_title = data.get("title")
            req_content = data.get("content")
    except Exception:
        # Ignore and try form data next
        req_title = None
        req_content = None
    # If JSON not provided or failed, try form
    if not req_title or not req_content:
        try:
            form = await request.form()
            req_title = req_title or form.get("title")
            req_content = req_content or form.get("content")
        except Exception:
            # fall through to validation error below
            pass

    if not req_title or not req_content:
        # Emit a brief debug hint to server logs
        try:
            size_hint = len(await request.body())
        except Exception:
            size_hint = -1
        logger.debug(f"[KB] add-markdown: missing fields. size={size_hint}")
        raise HTTPException(status_code=400, detail="Both 'title' and 'content' are required (JSON or form)")

    # Generate a document_id up-front so we can deterministically name storage path
    doc_id = str(uuid.uuid4())
    filename = f"{doc_id}.md"

    # Upload full content to Supabase Storage (primary store)
    try:
        supabase_storage.upload_markdown(client_id=client_id, filename=filename, content=req_content)
    except Exception:
        # Best-effort: continue; caller will notice if vectors/preview exist without blob
        pass

    # Create knowledge base metadata in DB (no full content)
    kb_entry = KnowledgeDocument(
        document_id=doc_id,
        client_id=client_id,
        title=req_title,
        content=None,
        content_preview=req_content[:2000],
        storage_path=f"{client_id}/markdowns/{filename}",
        source_url=None
    )
    db.add(kb_entry)
    db.commit()
    db.refresh(kb_entry)

    # Index into vector database using the full content from request
    vector_store = service_manager.get_vector_store_service(f"client_{client_id}")
    vector_store.add_text(
        req_content,
        metadata={
            "document_id": str(kb_entry.document_id),
            "client_id": client_id,
            "title": req_title,
            "source_url": "",
        },
    )

    return {
        "success": True,
        "message": "Markdown content added successfully",
        "document_id": str(kb_entry.document_id)
    }


@router.put("/entry/{document_id}")
async def update_markdown_content(
    document_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Update existing markdown content"""
    
    kb_entry = db.query(KnowledgeDocument).filter(KnowledgeDocument.document_id == document_id).first()
    if not kb_entry:
        raise HTTPException(status_code=404, detail="Knowledge base entry not found")
    
    # Update fields if provided
    if title:
        kb_entry.title = title
    if content:
        # Upload updated content to Supabase Storage; keep DB as metadata-only
        try:
            filename = f"{kb_entry.document_id}.md"
            supabase_storage.upload_markdown(client_id=str(kb_entry.client_id), filename=filename, content=content)
            # Ensure storage_path set
            if not kb_entry.storage_path:
                kb_entry.storage_path = f"{kb_entry.client_id}/markdowns/{filename}"
        except Exception:
            pass
        # Update preview and clear legacy content field
        kb_entry.content_preview = content[:2000]
        kb_entry.content = None

        # Replace vectors for this document: delete old chunks then add new
        vector_store = service_manager.get_vector_store_service(f"client_{kb_entry.client_id}")
        try:
            vector_store.delete_by_document_id(str(kb_entry.document_id))
        except Exception:
            pass
        vector_store.add_text(
            content,
            metadata={
                "document_id": str(kb_entry.document_id),
                "client_id": str(kb_entry.client_id),
                "title": kb_entry.title,
                "source_url": kb_entry.source_url or "",
            },
        )
    
    db.commit()
    db.refresh(kb_entry)
    
    return {
        "success": True,
        "message": "Knowledge base entry updated successfully",
        "entry": kb_entry
    }


@router.delete("/entry/{document_id}")
async def delete_markdown_content(document_id: str, db: Session = Depends(get_db)):
    """Delete markdown content from knowledge base"""
    
    kb_entry = db.query(KnowledgeDocument).filter(KnowledgeDocument.document_id == document_id).first()
    if not kb_entry:
        raise HTTPException(status_code=404, detail="Knowledge base entry not found")
    
    client_id = str(kb_entry.client_id)
    
    # Delete mirrored file from Supabase Storage (best effort)
    try:
        filename = f"{kb_entry.document_id}.md"
        supabase_storage.delete_markdown(client_id, filename)
    except Exception:
        pass
    
    # Delete vectors for this document_id within the client's collection (best effort)
    try:
        vector_store = service_manager.get_vector_store_service(f"client_{client_id}")
        vector_store.delete_by_document_id(str(kb_entry.document_id))
    except Exception:
        pass
    
    # Delete from database
    db.delete(kb_entry)
    db.commit()
    
    return {
        "success": True,
        "message": "Knowledge base entry deleted successfully"
    }


@router.post("/client/{client_id}/upload-file")
async def upload_markdown_file(
    client_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload markdown file to client's knowledge base"""
    
    if not file.filename.endswith(('.md', '.txt')):
        raise HTTPException(status_code=400, detail="Only .md and .txt files are supported")
    
    try:
        # Read file content
        content = await file.read()
        content_str = content.decode('utf-8')
        
        # Generate document_id and upload to Supabase first
        doc_id = str(uuid.uuid4())
        filename = f"{doc_id}.md"
        try:
            supabase_storage.upload_markdown(client_id=client_id, filename=filename, content=content_str)
        except Exception:
            pass
        # Save metadata only in DB
        kb_entry = KnowledgeDocument(
            document_id=doc_id,
            client_id=client_id,
            title=file.filename,
            content=None,
            content_preview=content_str[:2000],
            storage_path=f"{client_id}/markdowns/{filename}",
            source_url=None
        )
        
        db.add(kb_entry)
        db.commit()
        db.refresh(kb_entry)
        
        # Update vector database
        vector_store = service_manager.get_vector_store_service(f"client_{client_id}")
        vector_store.add_text(
            content_str,
            metadata={
                "document_id": str(kb_entry.document_id),
                "client_id": client_id,
                "title": file.filename,
                "source_url": "",
            },
        )
        
        return {
            "success": True,
            "message": f"File {file.filename} uploaded successfully",
            "document_id": str(kb_entry.document_id)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")


@router.post("/client/{client_id}/rebuild-vectors")
async def rebuild_vector_database(client_id: str, db: Session = Depends(get_db)):
    """Rebuild vector database for client from all knowledge base entries"""
    
    try:
        # Get all knowledge base entries for client
        kb_entries = db.query(KnowledgeDocument).filter(
            KnowledgeDocument.client_id == client_id
        ).all()
        
        if not kb_entries:
            return {
                "success": True,
                "message": "No knowledge base entries found for client"
            }
        
        # Rebuild vector store
        vector_store = service_manager.get_vector_store_service(f"client_{client_id}")
        vector_store.delete_collection() # Clear old vectors
        
        # Add all documents back to the store (read exclusively from Supabase Storage)
        for entry in kb_entries:
            try:
                filename = f"{entry.document_id}.md"
                content = supabase_storage.download_markdown(str(entry.client_id), filename)
            except Exception:
                content = None
            if not content:
                continue
            vector_store.add_text(
                content,
                metadata={
                    "document_id": str(entry.document_id),
                    "client_id": str(entry.client_id),
                    "title": entry.title,
                    "source_url": entry.source_url or "",
                },
            )
        
        return {
            "success": True,
            "message": f"Vector database rebuilt with {len(kb_entries)} entries",
            "entries_processed": len(kb_entries)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error rebuilding vectors: {str(e)}")


@router.get("/client/{client_id}/search")
async def search_knowledge_base(
    client_id: str,
    query: str,
    limit: int = 5,
    db: Session = Depends(get_db)
):
    """Search client's knowledge base using vector similarity"""
    
    try:
        vector_store = service_manager.get_vector_store_service(f"client_{client_id}")
        results = vector_store.query(query, k=limit)
        # Serialize LangChain Documents to JSON-friendly dicts
        results = [
            {"page_content": getattr(doc, "page_content", ""), "metadata": getattr(doc, "metadata", {})}
            for doc in results
        ]

        return {
            "success": True,
            "query": query,
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching knowledge base: {str(e)}")


# --------- Supabase Storage utilities (admin) ---------
@router.get("/client/{client_id}/storage/markdowns")
async def list_storage_markdowns(client_id: str, _: Session = Depends(get_db)):
    """List markdown files mirrored in Supabase Storage for a client"""
    try:
        files = supabase_storage.list_markdowns(client_id)
        return {"client_id": client_id, "files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Storage list failed: {e}")


@router.get("/client/{client_id}/storage/markdown")
async def get_storage_markdown(client_id: str, filename: str, _: Session = Depends(get_db)):
    """Download a mirrored markdown file from Supabase Storage"""
    try:
        content = supabase_storage.download_markdown(client_id, filename)
        if content is None:
            raise HTTPException(status_code=404, detail="File not found in storage")
        return {"filename": filename, "content": content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Storage download failed: {e}")


@router.post("/client/{client_id}/storage/markdowns")
async def create_markdown_in_storage(
    client_id: str,
    title: str = Form(...),
    content: str = Form(...),
    db: Session = Depends(get_db)
):
    """Create a new markdown file directly in storage and index it into DB + vectors"""
    try:
        # Generate document_id and upload to Supabase first
        doc_id = str(uuid.uuid4())
        filename = f"{doc_id}.md"
        try:
            supabase_storage.upload_markdown(client_id=client_id, filename=filename, content=content)
        except Exception:
            pass

        # Save metadata only in DB
        kb_entry = KnowledgeDocument(
            document_id=doc_id,
            client_id=client_id,
            title=title,
            content=None,
            content_preview=content[:2000],
            storage_path=f"{client_id}/markdowns/{filename}",
            source_url=None
        )
        db.add(kb_entry)
        db.commit()
        db.refresh(kb_entry)

        # Index to vectors from provided content
        vector_store = service_manager.get_vector_store_service(f"client_{client_id}")
        vector_store.add_text(content, metadata={"document_id": str(kb_entry.document_id)})

        return {"success": True, "document_id": str(kb_entry.document_id), "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create markdown in storage: {e}")
