import os
from typing import List, Dict, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.memory import ConversationSummaryMemory, ConversationBufferMemory
from langchain.chains import ConversationChain
from app.config import settings


class MarkdownFilter:
    def __init__(self):
        self.llm = None
        self.chain = None
        
        # Only initialize if Google API key is available
        if hasattr(settings, 'google_api_key') and settings.google_api_key:
            try:
                self.llm = ChatGoogleGenerativeAI(
                    google_api_key=settings.google_api_key, 
                    model="gemma-3-27b-it", 
                    temperature=0
                )
                self.summary_memory = ConversationSummaryMemory(llm=self.llm)
                self.buffer_memory = ConversationBufferMemory()
                self.chain = ConversationChain(
                    llm=self.llm,
                    memory=self.summary_memory
                )
                print("Google Gemini LLM filter initialized")
            except Exception as e:
                print(f"Failed to initialize Gemini LLM: {e}")
    
    def is_available(self) -> bool:
        """Check if LLM filtering is available"""
        return self.chain is not None
    
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
                prompt = self._build_prompt(md['content'], user_prompt)
                result = self.chain.run(prompt)
                self.buffer_memory.save_context({"input": prompt}, {"output": result})
                
                # Only keep if LLM returns markdown (not NULL)
                if result.strip().upper() != "NULL":
                    # Replace content with LLM's improved markdown output
                    md['content'] = result.strip()
                    filtered.append(md)
                    
            except Exception as e:
                print(f"Error filtering markdown {md.get('filename', 'unknown')}: {e}")
                # Keep original on error
                filtered.append(md)
        
        return filtered
    
    def _build_prompt(self, markdown_content: str, user_prompt: str) -> str:
        """Build prompt for LLM filtering"""
        return (
            f"You are an expert at extracting information from websites for a retrieval-augmented generation (RAG) chatbot. "
            f"Your job is to filter and summarize markdown content. "
            f"The user request is: {user_prompt}\n"
            f"Given the following markdown content, extract ONLY the sections that directly answer the user request. "
            f"If there is relevant information, return ONLY the relevant markdown (no prose, no explanation, just markdown, no repetition). "
            f"If nothing is relevant, return 'NULL'.\n\n"
            f"Markdown Content:\n{markdown_content}\n"
        )


# Global instance
markdown_filter = MarkdownFilter()