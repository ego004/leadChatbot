import asyncio
import os
from typing import Optional, List, Dict
from sqlalchemy.orm import Session

from app.models.client import Client, IngestionStatus
from app.models.knowledge_base import KnowledgeDocument
from app.services.crawler import crawl_website, read_and_combine_markdown_files, cleanup_temp_files
from app.services.llm_filter import markdown_filter
from app.services.vector_store_service import VectorStoreService


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
        """Crawl website, optionally LLM-filter markdown, store KnowledgeDocuments, rebuild vector store."""
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
                            markdown_items.append({
                                "filename": os.path.basename(path),
                                "content": content,
                                "source_url": website_url,
                            })
                except Exception:
                    continue

            # Optional LLM filtering
            if user_prompt and markdown_filter.is_available():
                markdown_items = markdown_filter.filter_markdown_files(markdown_items, user_prompt)

            # Store as KnowledgeDocuments (replace existing docs for this source)
            # Simple strategy: delete existing docs with same source_url
            if markdown_items:
                db.query(KnowledgeDocument).filter(
                    KnowledgeDocument.client_id == client_id,
                    KnowledgeDocument.source_url == website_url
                ).delete()
                db.commit()

            new_docs: List[KnowledgeDocument] = []
            for md in markdown_items:
                doc = KnowledgeDocument(
                    client_id=client_id,
                    title=md.get("filename") or "Scraped Page",
                    content=md.get("content", ""),
                    source_url=md.get("source_url") or website_url,
                )
                db.add(doc)
                new_docs.append(doc)
            db.commit()
            for d in new_docs:
                db.refresh(d)

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
        """Delete and rebuild the client's vector collection from KnowledgeDocuments."""
        collection = self._collection_name(client_id)
        vs = VectorStoreService(collection_name=collection)
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
            vs.add_text(doc.content, metadata={"document_id": doc.document_id, "client_id": client_id, "title": doc.title})

    def add_or_update_document_in_vectors(self, client_id: str, document: KnowledgeDocument) -> None:
        collection = self._collection_name(client_id)
        vs = VectorStoreService(collection_name=collection)
        vs.add_text(document.content, metadata={"document_id": document.document_id, "client_id": client_id, "title": document.title})

    def delete_vectors_for_client(self, client_id: str) -> None:
        collection = self._collection_name(client_id)
        vs = VectorStoreService(collection_name=collection)
        vs.delete_collection()
