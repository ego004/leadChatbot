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
import uuid


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
        # Reset per-client LLM memory at the start of a cleaning run to avoid cross-run carryover
        try:
            markdown_filter.reset_client_memory(client_id)
        except Exception:
            pass
        
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
        
        # Supabase Storage is the source of truth. Remove all existing blobs for client and re-upload.
        supabase_storage.delete_all_client_markdowns(client_id)

        # Database holds metadata only (no full content). Clear existing documents for client.
        from app.models.knowledge_base import KnowledgeDocument
        db.query(KnowledgeDocument).filter(KnowledgeDocument.client_id == client_id).delete()

        # Track created docs for vector indexing
        created_docs: list[tuple[str, str | None, str]] = []  # (document_id, source_url, content)

        # Create KB entries with deterministic storage filenames by document_id and upload full content
        for md in markdowns:
            # Derive a reasonable title: first H1 if present, else filename without .md
            title = md.get("filename", "").replace(".md", "") or (md["content"].splitlines()[0].strip("# ") if md.get("content") else "Document")
            source_url = md.get("source_url")
            content = md["content"]

            doc_id = str(uuid.uuid4())
            filename = f"{doc_id}.md"

            # Upload full content to Supabase Storage
            supabase_storage.upload_markdown(
                client_id=client_id,
                filename=filename,
                content=content,
            )

            # Persist metadata-only record in DB
            doc = KnowledgeDocument(
                document_id=doc_id,
                client_id=client_id,
                title=title,
                content=None,
                content_preview=content[:2000],
                storage_path=f"{client_id}/markdowns/{filename}",
                source_url=source_url,
            )
            db.add(doc)
            created_docs.append((doc_id, source_url, content))

        # Rebuild vector store for client
        vector_store = VectorStoreService(collection_name=f"client_{client_id}")
        vector_store.delete_collection()

        # Index with rich metadata
        for (doc_id, source_url, content) in created_docs:
            doc_metadata = {
                "document_id": doc_id,
                "client_id": client_id,
                "source_url": source_url or "",
            }
            vector_store.add_text(content, metadata=doc_metadata)
        
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
            # Fail fast if nothing was scraped
            if not file_paths:
                print(f"[INGEST] _scrape_sync: 0 pages scraped for client={client_id}, url={client.website_url}")
                raise Exception("No pages scraped from website. Check website_url or crawler settings.")

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

        # Reset per-client LLM memory at the start of a cleaning run to avoid cross-run carryover
        try:
            markdown_filter.reset_client_memory(client_id)
        except Exception:
            pass

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

        # If no markdowns were produced, fail fast
        if not markdowns:
            print(f"[INGEST] _chunk_and_embed_sync: 0 markdowns to index for client={client_id}")
            raise Exception("No markdowns generated from crawl/clean phases.")

        # Supabase Storage is the source of truth: clear and re-upload under document_id filenames
        try:
            supabase_storage.delete_all_client_markdowns(client_id)
        except Exception:
            pass

        # Reset DB metadata for client
        from app.models.knowledge_base import KnowledgeDocument
        db.query(KnowledgeDocument).filter(KnowledgeDocument.client_id == client_id).delete()

        created: list[tuple[str, str | None, str]] = []  # (document_id, source_url, content)
        for md in markdowns:
            content = md["content"]
            source_url = md.get("source_url")
            title = (md.get("filename") or "document.md").replace(".md", "")

            doc_id = str(uuid.uuid4())
            filename = f"{doc_id}.md"

            # Upload full content to storage
            try:
                supabase_storage.upload_markdown(client_id=client_id, filename=filename, content=content)
            except Exception:
                pass

            # Persist metadata-only record
            doc = KnowledgeDocument(
                document_id=doc_id,
                client_id=client_id,
                title=title,
                content=None,
                content_preview=content[:2000],
                storage_path=f"{client_id}/markdowns/{filename}",
                source_url=source_url,
            )
            db.add(doc)
            created.append((doc_id, source_url, content))

        # Vector store build (aligned collection name)
        vector_store = VectorStoreService(collection_name=f"client_{client_id}")
        vector_store.delete_collection()
        # Strictly re-download content from Supabase Storage to index, ensuring Storage is the sole source
        for (doc_id, source_url, _content) in created:
            try:
                filename = f"{doc_id}.md"
                content = supabase_storage.download_markdown(client_id, filename)
            except Exception:
                content = None
            if not content:
                continue
            vector_store.add_text(content, metadata={
                "document_id": doc_id,
                "client_id": client_id,
                "source_url": source_url or "",
            })

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
