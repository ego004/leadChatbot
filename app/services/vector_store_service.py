from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from typing import List, Optional
import logging
from app.config import settings

# Vector stores
from langchain_community.vectorstores import SupabaseVectorStore  # type: ignore
from supabase import create_client, Client  # type: ignore

from langchain_community.embeddings import SentenceTransformerEmbeddings

logging.basicConfig(level=logging.INFO)

# Cache a single SentenceTransformerEmbeddings instance process-wide
_EMBEDDINGS_SINGLETON: Optional[SentenceTransformerEmbeddings] = None

def preload_embeddings():
    """Preload the SentenceTransformer embeddings singleton.
    This avoids first-request latency and repeated model loads.
    Safe to call multiple times.
    """
    global _EMBEDDINGS_SINGLETON
    if _EMBEDDINGS_SINGLETON is None:
        model_name = getattr(settings, "embeddings_model_name", None) or "all-MiniLM-L6-v2"
        _EMBEDDINGS_SINGLETON = SentenceTransformerEmbeddings(model_name=model_name)
        logging.info(f"Preloaded SentenceTransformerEmbeddings singleton: {model_name}")

class VectorStoreService:
    """
    Vector store service (Supabase only).
    - Requires SUPABASE_URL and SUPABASE_KEY in `app.config.settings`.
    - Uses Supabase pgvector via `SupabaseVectorStore` with table `documents` (configurable).

    collection_name is stored in metadata as {"collection": collection_name} to enable scoped deletes/queries.
    """

    def __init__(self, collection_name: str, table_name: str = "documents"):
        self.collection_name = collection_name
        self.table_name = table_name
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=80,
        )

        # Embeddings: enforce SentenceTransformers singleton only
        global _EMBEDDINGS_SINGLETON
        if _EMBEDDINGS_SINGLETON is None:
            raise RuntimeError(
                "SentenceTransformer embeddings not preloaded! "
                "Call preload_embeddings() during app startup before creating VectorStoreService instances."
            )
        self.embedding_function = _EMBEDDINGS_SINGLETON

        # Backend selection (Supabase only)
        self._backend: str = "supabase"
        self._supabase_client: Optional[Client] = None
        self.vector_store = None

        # Require Supabase configuration
        if not getattr(settings, "supabase_url", None) or not getattr(settings, "supabase_key", None):
            raise RuntimeError("Supabase is required but not configured. Please set SUPABASE_URL and SUPABASE_KEY.")

        try:
            self._supabase_client = create_client(settings.supabase_url, settings.supabase_key)
            # Initialize vector store handle; we'll use add_texts/add_documents on demand
            self.vector_store = SupabaseVectorStore(
                client=self._supabase_client,
                embedding=self.embedding_function,
                table_name=self.table_name,
                query_name="match_documents",
                chunk_size=100,
            )
            logging.info("Using SupabaseVectorStore backend")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize SupabaseVectorStore: {e}")

    def add_documents(self, documents: List[Document]):
        if not documents:
            return
        try:
            # Ensure collection metadata is attached for Supabase to filter later
            if self._backend == "supabase":
                for d in documents:
                    d.metadata = {**(d.metadata or {}), "collection": self.collection_name}
            self.vector_store.add_documents(documents=documents)
            logging.info(f"Added {len(documents)} chunks to collection {self.collection_name}")
        except Exception as e:
            logging.error(f"Failed to add documents to vector store: {e}")

    def add_text(self, text: str, metadata: dict = None):
        if not metadata:
            metadata = {}
        chunks = self.text_splitter.split_text(text)
        doc_meta = {**metadata, "collection": self.collection_name} if self._backend == "supabase" else metadata
        documents = [Document(page_content=chunk, metadata=doc_meta) for chunk in chunks]
        self.add_documents(documents)

    def query(self, query_text: str, k: int = 5) -> List[Document]:
        try:
            # Direct similarity search with filter by logical collection boundary
            return self.vector_store.similarity_search(
                query=query_text,
                k=k,
                filter={"collection": self.collection_name}
            )
        except Exception as e:
            logging.error(f"Failed to query vector store: {e}")
            return []

    def delete_collection(self):
        try:
            # Delete rows from the underlying table for this logical collection
            if not self._supabase_client:
                return
            table = self._supabase_client.table(self.table_name)
            # The supabase-py client supports filter("metadata->>collection", "eq", value)
            table.delete().filter("metadata->>collection", "eq", self.collection_name).execute()
            logging.info(f"Deleted Supabase vectors for collection {self.collection_name}")
        except Exception as e:
            logging.error(f"Failed to delete collection {self.collection_name}: {e}")

    def delete_by_document_id(self, document_id: str):
        """Delete all vector rows for a given document_id within this collection."""
        try:
            if not self._supabase_client:
                return
            table = self._supabase_client.table(self.table_name)
            # Both collection and document_id are stored in metadata
            table.delete() \
                .filter("metadata->>collection", "eq", self.collection_name) \
                .filter("metadata->>document_id", "eq", str(document_id)) \
                .execute()
            logging.info(f"Deleted vectors for document_id={document_id} in collection {self.collection_name}")
        except Exception as e:
            logging.error(f"Failed to delete vectors for document {document_id} in {self.collection_name}: {e}")
