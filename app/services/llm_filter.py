import os
from typing import List, Dict, Any, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from app.config import settings


class MarkdownFilter:
    def __init__(self):
        self.llm = None
        # Per-client, in-process memory of previously retained content (simple buffer)
        # key: client_id (str) -> value: concatenated markdown retained so far (str)
        self._memory: Dict[str, str] = {}
        
        # Only initialize if Google API key is available
        if hasattr(settings, 'google_api_key') and settings.google_api_key:
            try:
                self.llm = ChatGoogleGenerativeAI(
                    google_api_key=settings.google_api_key, 
                    model="gemma-3-27b-it", 
                    temperature=0
                )
                print("Google Gemini LLM filter initialized")
            except Exception as e:
                print(f"Failed to initialize Gemini LLM: {e}")
    
    def is_available(self) -> bool:
        """Check if LLM filtering is available"""
        return self.llm is not None
    
    def filter_markdown_files(self, markdowns: List[Dict[str, Any]], user_prompt: str) -> List[Dict[str, Any]]:
        """
        Filter and improve markdown content using LLM, optimising for using as a knowledge base for a RAG workflow.
        
        Args:
            markdowns: List of dicts with keys: filename, content, source_url, etc.
            user_prompt: Description of what to look for and website type
            
        Returns:
            Filtered list of markdowns with improved content
        """
        if not self.is_available():
            print("LLM filtering not available, returning original markdowns")
            return markdowns
        
        filtered = []
        for md in markdowns:
            try:
                client_id = md.get('client_id') or ""
                prev_context = self._memory.get(client_id, "") if client_id else ""
                prompt = self._build_prompt(md['content'], user_prompt, prev_context)
                # Stateless per-document call to avoid memory bleed across pages
                result = self.llm.predict(prompt)
                
                # Only keep if LLM returns markdown (not NULL)
                if result.strip().upper() != "NULL":
                    # Drop if output is totally contained within prior retained context
                    prior = self._memory.get(client_id, "") if client_id else ""
                    out = result.strip()
                    if prior and out and out in prior:
                        # Considered duplicate; skip keeping
                        continue
                    # Replace content with LLM's improved markdown output
                    md['content'] = result.strip()
                    filtered.append(md)
                    # Update memory buffer (truncate to last ~8k chars)
                    if client_id:
                        updated = (prior + "\n" + out) if prior else out
                        self._memory[client_id] = updated[-8000:]
                
            except Exception as e:
                print(f"Error filtering markdown {md.get('filename', 'unknown')}: {e}")
                # Keep original on error
                filtered.append(md)
        
        return filtered
    
    def _build_prompt(self, markdown_content: str, user_prompt: str, prev_context: Optional[str] = None) -> str:
        """Build prompt for LLM filtering"""
        prev_section = (
            "\nAlready kept content (do NOT repeat any overlapping content; if your output would be entirely repetitive, return 'NULL'):\n"
            f"{prev_context}\n"
            if prev_context and prev_context.strip() else ""
        )
        return (
            f"You are an expert at extracting information from websites for a retrieval-augmented generation (RAG) chatbot. "
            f"Your job is to filter and summarize markdown content. "
            f"The user request is: {user_prompt}\n"
            f"Given the following markdown content, extract ONLY the sections that directly answer the user request. "
            f"Rules: return ONLY markdown, no prose/explanations; STRICTLY avoid repeating any content already kept; if fully repetitive, return 'NULL'."
            f"{prev_section}\n"
            f"Markdown Content:\n{markdown_content}\n"
        )

    # Memory management helpers
    def reset_client_memory(self, client_id: str) -> None:
        """Reset memory buffer for a specific client."""
        if client_id in self._memory:
            del self._memory[client_id]

    def reset_all_memory(self) -> None:
        """Reset all memory buffers."""
        self._memory.clear()


# Global instance
markdown_filter = MarkdownFilter()