from supabase import create_client, Client
from typing import List, Dict, Any, Optional
import tempfile
import os
import uuid
from app.config import settings
import logging


logger = logging.getLogger(__name__)


class SupabaseStorageService:
    def __init__(self):
        self.client: Optional[Client] = None
        
        # Only initialize if Supabase credentials are provided
        if hasattr(settings, 'supabase_url') and hasattr(settings, 'supabase_key'):
            if settings.supabase_url and settings.supabase_key:
                try:
                    self.client = create_client(settings.supabase_url, settings.supabase_key)
                    logger.info("Supabase client initialized successfully")
                except Exception as e:
                    logger.warning(f"Failed to initialize Supabase client: {e}")
    
    def is_available(self) -> bool:
        """Check if Supabase is available"""
        return self.client is not None
    
    def upload_markdown(self, client_id: str, filename: str, content: str) -> bool:
        """Upload markdown content to Supabase Storage"""
        if not self.is_available():
            return False
        
        try:
            # Create temp file
            temp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}_{filename}")
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Upload to Supabase Storage
            bucket = self.client.storage.from_("leadgenius-markdowns")
            storage_path = f"{client_id}/markdowns/{filename}"
            
            with open(temp_path, 'rb') as f:
                result = bucket.upload(storage_path, f)
            
            # Clean up temp file
            os.remove(temp_path)
            
            return True
            
        except Exception as e:
            logger.warning(f"Error uploading markdown to Supabase: {e}")
            return False
    
    def download_markdown(self, client_id: str, filename: str) -> Optional[str]:
        """Download markdown content from Supabase Storage"""
        if not self.is_available():
            return None
        
        try:
            bucket = self.client.storage.from_("leadgenius-markdowns")
            storage_path = f"{client_id}/markdowns/{filename}"
            
            res = bucket.download(storage_path)
            
            if hasattr(res, 'decode'):
                content = res.decode('utf-8')
            else:
                content = res.read().decode('utf-8') if hasattr(res, 'read') else str(res)
            
            return content
            
        except Exception as e:
            logger.warning(f"Error downloading markdown from Supabase: {e}")
            return None
    
    def list_markdowns(self, client_id: str) -> List[str]:
        """List all markdown files for a client"""
        if not self.is_available():
            return []
        
        try:
            bucket = self.client.storage.from_("leadgenius-markdowns")
            folder_path = f"{client_id}/markdowns/"
            
            files = bucket.list(folder_path)
            return [file['name'] for file in files if file['name'].endswith('.md')]
            
        except Exception as e:
            logger.warning(f"Error listing markdowns from Supabase: {e}")
            return []
    
    def delete_markdown(self, client_id: str, filename: str) -> bool:
        """Delete markdown file from Supabase Storage"""
        if not self.is_available():
            return False
        
        try:
            bucket = self.client.storage.from_("leadgenius-markdowns")
            storage_path = f"{client_id}/markdowns/{filename}"
            
            bucket.remove([storage_path])
            return True
            
        except Exception as e:
            logger.warning(f"Error deleting markdown from Supabase: {e}")
            return False
    
    def delete_all_client_markdowns(self, client_id: str) -> bool:
        """Delete all markdown files for a client"""
        if not self.is_available():
            return False
        
        try:
            files = self.list_markdowns(client_id)
            if files:
                bucket = self.client.storage.from_("leadgenius-markdowns")
                storage_paths = [f"{client_id}/markdowns/{filename}" for filename in files]
                bucket.remove(storage_paths)
            
            return True
            
        except Exception as e:
            logger.warning(f"Error deleting all client markdowns from Supabase: {e}")
            return False


# Global instance
supabase_storage = SupabaseStorageService()
