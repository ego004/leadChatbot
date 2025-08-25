from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.client import Client, IngestionStatus
from app.services.crawler import crawl_website, read_and_combine_markdown_files, cleanup_temp_files
from app.services.vector_store_service import VectorStoreService
from app.services.supabase_storage import supabase_storage
from app.services.llm_filter import markdown_filter
from app.services.llm import llm_service
import asyncio
import os


def get_db_session():
    """Get database session for ingestion tasks"""
    return SessionLocal()


def task_scrape(client_id: str, max_depth: int = 3):
    """Crawl the client's website and return raw content"""
    db = get_db_session()
    try:
        # Get client info
        client = db.query(Client).filter(Client.client_id == client_id).first()
        if not client:
            raise Exception(f"Client {client_id} not found")
        
        # Update status to scraping
        client.ingestion_status = IngestionStatus.SCRAPING
        db.commit()
        
        # Crawl website
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            file_paths = loop.run_until_complete(
                crawl_website(client.website_url, max_depth=max_depth)
            )
            
            return {
                "client_id": client_id,
                "file_paths": file_paths,
                "website_url": client.website_url,
                "pages_crawled": len(file_paths)
            }
            
        finally:
            loop.close()
            
    except Exception as e:
        # Update status to failed
        client = db.query(Client).filter(Client.client_id == client_id).first()
        if client:
            client.ingestion_status = IngestionStatus.FAILED
            db.commit()
        db.close()
        raise e
    finally:
        db.close()


def task_clean(scrape_result, prompt: str | None = None, use_filter: bool = True):
    """Clean and filter content using LLM (like user's existing tool)"""
    try:
        client_id = scrape_result["client_id"]
        file_paths = scrape_result["file_paths"]
        
        # Read individual markdown files
        markdowns = []
        for file_path in file_paths:
            filename = os.path.basename(file_path)
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # Extract per-page source URL from the markdown header ("Source: ...")
            source_url = scrape_result.get("website_url", "")
            for line in content.splitlines():
                if line.strip().lower().startswith("source:"):
                    source_url = line.split(":", 1)[1].strip()
                    break

            markdowns.append({
                "filename": filename,
                "content": content,
                "source_url": source_url,
                "client_id": client_id
            })
        
        # Apply LLM filtering if available
        if use_filter and markdown_filter.is_available():
            # Get client info for filtering prompt
            db = get_db_session()
            try:
                client = db.query(Client).filter(Client.client_id == client_id).first()
                filter_prompt = prompt or (
                    f"Extract information relevant for a {client.name if client else 'business'} chatbot from their website content."
                )
                markdowns = markdown_filter.filter_markdown_files(markdowns, filter_prompt)
            finally:
                db.close()
        
        return {
            "client_id": client_id,
            "markdowns": markdowns,
            "pages_crawled": len(markdowns)
        }
        
    except Exception as e:
        # Update client status to failed
        db = get_db_session()
        try:
            client = db.query(Client).filter(Client.client_id == scrape_result["client_id"]).first()
            if client:
                client.ingestion_status = IngestionStatus.FAILED
                db.commit()
        finally:
            db.close()
        raise e


def task_chunk_and_embed(clean_result):
    """Store markdowns and create vector embeddings"""
    db = get_db_session()
    try:
        client_id = clean_result["client_id"]
        markdowns = clean_result["markdowns"]
        
        # Get client for system prompt generation
        client = db.query(Client).filter(Client.client_id == client_id).first()
        if not client:
            raise Exception(f"Client {client_id} not found")
        
        # Store markdowns in Supabase Storage
        if supabase_storage.is_available():
            # Delete existing markdowns
            supabase_storage.delete_all_client_markdowns(client_id)
            
            # Upload new markdowns
            for md in markdowns:
                supabase_storage.upload_markdown(
                    client_id=client_id,
                    filename=md["filename"],
                    content=md["content"]
                )
        
        # Store in database as backup
        from app.models.knowledge_base import KnowledgeDocument
        # Delete existing documents
        db.query(KnowledgeDocument).filter(KnowledgeDocument.client_id == client_id).delete()
        
        # Add new documents
        for md in markdowns:
            doc = KnowledgeDocument(
                client_id=client_id,
                title=md["filename"].replace(".md", ""),
                content=md["content"],
                source_url=md.get("source_url")
            )
            db.add(doc)
        
        # Rebuild vector store using the same collection naming as KB endpoints
        vector_store = VectorStoreService(collection_name=f"client_{client_id}")
        vector_store.delete_collection()  # Clear old vectors

        # Add new documents with metadata
        for md in markdowns:
            doc_metadata = {
                "filename": md.get("filename", ""),
                "source_url": md.get("source_url", "")
            }
            vector_store.add_text(md["content"], metadata=doc_metadata)
        
        # Update status to completed
        client.ingestion_status = IngestionStatus.COMPLETED
        db.commit()
        
        # Clean up temp files
        if "file_paths" in clean_result:
            cleanup_temp_files(clean_result["file_paths"])
        
        return {
            "client_id": client_id,
            "status": "completed",
            "pages_processed": clean_result["pages_crawled"],
            "markdowns_stored": len(markdowns)
        }
        
    except Exception as e:
        # Update status to failed
        client = db.query(Client).filter(Client.client_id == clean_result["client_id"]).first()
        if client:
            client.ingestion_status = IngestionStatus.FAILED
            db.commit()
        raise e
    finally:
        db.close()


def start_ingestion_pipeline(client_id: str):
    """Deprecated: Celery-based pipeline disabled. Use run_ingestion_pipeline_sync instead."""
    raise RuntimeError("Celery-based ingestion is disabled. Use run_ingestion_pipeline_sync().")


# -------------------------
# Synchronous (non-Celery) helpers
# -------------------------

def _scrape_sync(client_id: str, max_depth: int = 3):
    db = get_db_session()
    try:
        client = db.query(Client).filter(Client.client_id == client_id).first()
        if not client:
            raise Exception(f"Client {client_id} not found")

        client.ingestion_status = IngestionStatus.SCRAPING
        db.commit()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            file_paths = loop.run_until_complete(
                crawl_website(client.website_url, max_depth=max_depth)
            )
            return {
                "client_id": client_id,
                "file_paths": file_paths,
                "website_url": client.website_url,
                "pages_crawled": len(file_paths),
            }
        finally:
            loop.close()
    except Exception as e:
        client = db.query(Client).filter(Client.client_id == client_id).first()
        if client:
            client.ingestion_status = IngestionStatus.FAILED
            db.commit()
        raise e
    finally:
        db.close()


def _clean_sync(scrape_result: dict, prompt: str | None = None, use_filter: bool = True):
    try:
        client_id = scrape_result["client_id"]
        file_paths = scrape_result["file_paths"]

        markdowns = []
        for file_path in file_paths:
            filename = os.path.basename(file_path)
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Extract per-page source URL from the markdown header ("Source: ...")
            source_url = scrape_result.get("website_url", "")
            for line in content.splitlines():
                if line.strip().lower().startswith("source:"):
                    source_url = line.split(":", 1)[1].strip()
                    break
            markdowns.append(
                {
                    "filename": filename,
                    "content": content,
                    "source_url": source_url,
                    "client_id": client_id,
                }
            )

        if use_filter and markdown_filter.is_available():
            db = get_db_session()
            try:
                client = db.query(Client).filter(Client.client_id == client_id).first()
                filter_prompt = prompt or (
                    f"Extract information relevant for a {client.name if client else 'business'} chatbot from their website content."
                )
                markdowns = markdown_filter.filter_markdown_files(markdowns, filter_prompt)
            finally:
                db.close()

        return {
            "client_id": client_id,
            "markdowns": markdowns,
            "pages_crawled": len(markdowns),
        }
    except Exception as e:
        db = get_db_session()
        try:
            client = db.query(Client).filter(Client.client_id == scrape_result["client_id"]).first()
            if client:
                client.ingestion_status = IngestionStatus.FAILED
                db.commit()
        finally:
            db.close()
        raise e


def _chunk_and_embed_sync(clean_result: dict):
    db = get_db_session()
    try:
        client_id = clean_result["client_id"]
        markdowns = clean_result["markdowns"]

        client = db.query(Client).filter(Client.client_id == client_id).first()
        if not client:
            raise Exception(f"Client {client_id} not found")

        # Store markdowns in Supabase Storage
        if supabase_storage.is_available():
            supabase_storage.delete_all_client_markdowns(client_id)
            for md in markdowns:
                supabase_storage.upload_markdown(
                    client_id=client_id, filename=md["filename"], content=md["content"]
                )

        # Store in database as backup
        from app.models.knowledge_base import KnowledgeDocument
        db.query(KnowledgeDocument).filter(KnowledgeDocument.client_id == client_id).delete()
        for md in markdowns:
            doc = KnowledgeDocument(
                client_id=client_id,
                title=md["filename"].replace(".md", ""),
                content=md["content"],
                source_url=md.get("source_url"),
            )
            db.add(doc)

        # Vector store build (aligned collection name)
        vector_store = VectorStoreService(collection_name=f"client_{client_id}")
        vector_store.delete_collection()
        for md in markdowns:
            doc_metadata = {"filename": md.get("filename", ""), "source_url": md.get("source_url", "")}
            vector_store.add_text(md["content"], metadata=doc_metadata)

        client.ingestion_status = IngestionStatus.COMPLETED
        db.commit()

        if "file_paths" in clean_result:
            cleanup_temp_files(clean_result["file_paths"])

        return {
            "client_id": client_id,
            "status": "completed",
            "pages_processed": clean_result["pages_crawled"],
            "markdowns_stored": len(markdowns),
        }
    except Exception as e:
        client = db.query(Client).filter(Client.client_id == clean_result["client_id"]).first()
        if client:
            client.ingestion_status = IngestionStatus.FAILED
            db.commit()
        raise e
    finally:
        db.close()


def run_ingestion_pipeline_sync(client_id: str, max_depth: int = 3, prompt: str | None = None, use_filter: bool = False):
    """Run the ingestion pipeline synchronously (no Celery)."""
    scrape_result = _scrape_sync(client_id, max_depth=max_depth)
    clean_result = _clean_sync(scrape_result, prompt=prompt, use_filter=use_filter)
    final_result = _chunk_and_embed_sync(clean_result)
    return final_result
