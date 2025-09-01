import asyncio
import os
from typing import Optional, List, Dict
import uuid
from sqlalchemy.orm import Session

from app.models.client import Client, IngestionStatus
from app.models.knowledge_base import KnowledgeDocument
from app.services.crawler import crawl_website, read_and_combine_markdown_files, cleanup_temp_files
from app.services.llm_filter import markdown_filter
from app.services.service_manager import service_manager
from app.services.supabase_storage import supabase_storage


class IngestionService:
    def __init__(self, collection_prefix: str = "client_"):
        self.collection_prefix = collection_prefix

    def _collection_name(self, client_id: str) -> str:
        return f"{self.collection_prefix}{client_id}"

    async def ingest_client_website(
        self,
        db: Session,
        client_id: str,
        website_url: str,
        user_prompt: Optional[str] = None,
    ) -> Dict[str, str]:
        """Crawl website, optionally LLM-filter markdown, store KnowledgeDocuments (metadata only),
        mirror full markdown to Supabase Storage, and rebuild vector store from storage."""
        client: Client = db.query(Client).filter(Client.client_id == client_id).first()
        if not client:
            return {"status": "error", "message": "Client not found"}

        # Mark status SCRAPING
        client.ingestion_status = IngestionStatus.SCRAPING
        db.commit()

        saved_files: List[str] = []
        try:
            saved_files = await crawl_website(website_url)
            # Build markdown items list
            markdown_items: List[Dict[str, str]] = []
            for path in saved_files:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                        if content.strip():
                            # Extract per-page source URL from the markdown header ("Source: ...")
                            source_url = website_url
                            for line in content.splitlines():
                                if line.strip().lower().startswith("source:"):
                                    source_url = line.split(":", 1)[1].strip()
                                    break
                            markdown_items.append({
                                "filename": os.path.basename(path),
                                "content": content,
                                "source_url": source_url,
                                "client_id": client_id,
                            })
                except Exception:
                    continue

            # Optional LLM filtering
            if user_prompt and markdown_filter.is_available():
                # Reset per-run memory for this client to avoid cross-run carryover
                try:
                    markdown_filter.reset_client_memory(client_id)
                except Exception:
                    pass
                markdown_items = markdown_filter.filter_markdown_files(markdown_items, user_prompt)

            # Replace all existing documents for this client (fresh ingestion)
            if markdown_items:
                db.query(KnowledgeDocument).filter(
                    KnowledgeDocument.client_id == client_id
                ).delete()
                db.commit()
                # Also clear all mirrored blobs in storage so DB and storage stay in sync
                try:
                    supabase_storage.delete_all_client_markdowns(client_id)
                except Exception:
                    pass

            new_docs: List[KnowledgeDocument] = []
            for md in markdown_items:
                content = md.get("content", "")
                title = md.get("filename") or "scraped.md"
                # Create metadata-only record with explicit document_id for deterministic filename
                doc_id = str(uuid.uuid4())
                doc = KnowledgeDocument(
                    document_id=doc_id,
                    client_id=client_id,
                    title=title,
                    content=None,
                    content_preview=content[:2000] if content else None,
                    source_url=md.get("source_url") or website_url,
                )
                db.add(doc)
                # Upload full content to Supabase Storage under {document_id}.md and set storage_path
                try:
                    filename = f"{doc_id}.md"
                    supabase_storage.upload_markdown(client_id=client_id, filename=filename, content=content)
                    doc.storage_path = f"{client_id}/markdowns/{filename}"
                except Exception:
                    # Proceed even if upload fails; rebuild will skip missing content
                    pass
                # Ensure legacy content is not stored
                doc.content = None
                new_docs.append(doc)
            db.commit()

            # Rebuild vector store for the client
            self.rebuild_vectors_for_client(db, client_id)

            client.ingestion_status = IngestionStatus.COMPLETED
            db.commit()
            return {"status": "ok", "message": f"Ingested {len(new_docs)} documents"}
        except Exception as e:
            client.ingestion_status = IngestionStatus.FAILED
            db.commit()
            return {"status": "error", "message": str(e)}
        finally:
            if saved_files:
                cleanup_temp_files(saved_files)

    def rebuild_vectors_for_client(self, db: Session, client_id: str) -> None:
        """Delete and rebuild the client's vector collection from KnowledgeDocuments.
        Read markdown exclusively from Supabase Storage (no DB fallback)."""
        collection = self._collection_name(client_id)
        vs = service_manager.get_vector_store_service(collection)
        # Drop and rebuild
        try:
            vs.delete_collection()
        except Exception:
            pass
        documents = db.query(KnowledgeDocument).filter(
            KnowledgeDocument.client_id == client_id,
            KnowledgeDocument.is_active == True
        ).all()
        for doc in documents:
            try:
                filename = f"{doc.document_id}.md"
                content = supabase_storage.download_markdown(str(client_id), filename)
            except Exception:
                content = None
            if not content:
                # Skip documents missing in storage
                continue
            vs.add_text(
                content,
                metadata={
                    "document_id": doc.document_id,
                    "client_id": client_id,
                    "title": doc.title,
                    "source_url": doc.source_url or "",
                },
            )

    def add_or_update_document_in_vectors(self, client_id: str, document: KnowledgeDocument) -> None:
        collection = self._collection_name(client_id)
        vs = service_manager.get_vector_store_service(collection)
        try:
            filename = f"{document.document_id}.md"
            content = supabase_storage.download_markdown(str(client_id), filename)
        except Exception:
            content = None
        if not content:
            return
        vs.add_text(
            content,
            metadata={
                "document_id": document.document_id,
                "client_id": client_id,
                "title": document.title,
                "source_url": document.source_url or "",
            },
        )

    def delete_vectors_for_client(self, client_id: str) -> None:
        collection = self._collection_name(client_id)
        vs = service_manager.get_vector_store_service(collection)
        vs.delete_collection()
