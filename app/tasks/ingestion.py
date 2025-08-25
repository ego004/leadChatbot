from celery import chain
from sqlalchemy.orm import Session
from app.tasks.celery_app import celery_app
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
    """Get database session for Celery tasks"""
    return SessionLocal()


@celery_app.task(bind=True)
def task_scrape(self, client_id: str):
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
                crawl_website(client.website_url, max_depth=2)
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


@celery_app.task(bind=True)
def task_clean(self, scrape_result):
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
            
            markdowns.append({
                "filename": filename,
                "content": content,
                "source_url": scrape_result.get("website_url", ""),
                "client_id": client_id
            })
        
        # Apply LLM filtering if available
        if markdown_filter.is_available():
            # Get client info for filtering prompt
            db = get_db_session()
            try:
                client = db.query(Client).filter(Client.client_id == client_id).first()
                filter_prompt = f"Extract information relevant for a {client.name if client else 'business'} chatbot from their website content."
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


@celery_app.task(bind=True)
def task_chunk_and_embed(self, clean_result):
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
        
        # Rebuild vector store with ChromaDB
        vector_store = VectorStoreService(collection_name=client_id)
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
    """Start the complete ingestion pipeline"""
    # Create a chain of tasks
    pipeline = chain(
        task_scrape.s(client_id),
        task_clean.s(),
        task_chunk_and_embed.s()
    )
    
    # Execute the chain
    result = pipeline.apply_async()
    return result.id
