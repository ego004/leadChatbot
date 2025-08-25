import pdfplumber
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from typing import List, Optional
import logging
from app.config import settings

# Embeddings: prefer Google Generative AI if configured, otherwise sentence-transformers
try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings  # type: ignore
except Exception:  # pragma: no cover
    GoogleGenerativeAIEmbeddings = None  # type: ignore

# Vector stores
from langchain_community.vectorstores import SupabaseVectorStore  # type: ignore
from supabase import create_client, Client  # type: ignore

from langchain_community.embeddings import SentenceTransformerEmbeddings

logging.basicConfig(level=logging.INFO)

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
            chunk_size=1000,
            chunk_overlap=100,
        )

        # Embedding selection
        # Default to local embeddings unless explicitly configured to 'google'
        self.embedding_function = None
        provider = getattr(settings, "embeddings_provider", "local")
        if provider == "google" and getattr(settings, "google_api_key", None) and GoogleGenerativeAIEmbeddings is not None:
            self.embedding_function = GoogleGenerativeAIEmbeddings(
                google_api_key=settings.google_api_key,
                model="models/embedding-001",
            )
        else:
            self.embedding_function = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")

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
                chunk_size=500,
            )
            logging.info("Using SupabaseVectorStore backend")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize SupabaseVectorStore: {e}")

    def pdf_to_chunks(self, file_path: str, filename: str) -> List[Document]:
        pdf_chunks = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        for chunk in self.text_splitter.split_text(text):
                            pdf_chunks.append(Document(
                                page_content=chunk,
                                metadata={"filename": filename, "page": i}
                            ))
            return pdf_chunks
        except Exception as e:
            logging.error(f"Failed to process PDF {filename}: {e}")
            return []

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
            # Filter by our logical collection boundary
            retriever = self.vector_store.as_retriever(search_kwargs={"k": k, "filter": {"collection": self.collection_name}})
            return retriever.get_relevant_documents(query_text)
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
