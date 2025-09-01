"""
Service Manager for singleton instances to improve performance.
Eliminates per-request instantiation overhead.
"""
from typing import Dict, Optional
import logging
from app.services.vector_store_service import VectorStoreService
from app.services.gemini_service import GeminiService
from app.services.lead_service import LeadService

logger = logging.getLogger(__name__)

class ServiceManager:
    """Manages singleton service instances to avoid per-request instantiation overhead"""
    
    _instance: Optional['ServiceManager'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        # Only initialize once
        if not ServiceManager._initialized:
            self._gemini_service: Optional[GeminiService] = None
            self._vector_store_cache: Dict[str, VectorStoreService] = {}
            ServiceManager._initialized = True
        
    def get_gemini_service(self) -> GeminiService:
        """Get or create singleton GeminiService instance"""
        if self._gemini_service is None:
            self._gemini_service = GeminiService()
            logger.info("✅ GeminiService singleton initialized")
        return self._gemini_service
    
    def get_vector_store_service(self, collection_name: str) -> VectorStoreService:
        """Get or create cached VectorStoreService for collection"""
        if collection_name not in self._vector_store_cache:
            self._vector_store_cache[collection_name] = VectorStoreService(collection_name)
            logger.info(f"✅ VectorStoreService cached for collection: {collection_name}")
        return self._vector_store_cache[collection_name]
    
    def get_lead_service(self, db) -> LeadService:
        """Get LeadService instance (lightweight, no caching needed)"""
        return LeadService(db)
    
    def preload_services(self):
        """Preload all services during startup"""
        try:
            # Preload Gemini service
            self.get_gemini_service()
            logger.info("✅ ServiceManager: All services preloaded")
        except Exception as e:
            logger.error(f"⚠️ ServiceManager preload failed: {e}")

# Global singleton instance - use getter function to ensure proper initialization
def get_service_manager() -> ServiceManager:
    """Get the singleton ServiceManager instance"""
    return ServiceManager()

# For backward compatibility, create the instance
service_manager = get_service_manager()
