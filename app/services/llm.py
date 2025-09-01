from typing import Dict, Any, List
import asyncio
import json
from app.config import settings
from app.services.service_manager import service_manager


class LLMService:
    def __init__(self):
        # Use cached Gemini service to avoid repeated initialization
        self.gemini = service_manager.get_gemini_service()
    
    def generate_system_prompt(self, client_name: str, website_url: str) -> str:
        """Generate a system prompt for the client's chatbot"""
        return f"""You are an AI assistant for {client_name} (website: {website_url}). 

Your primary goals are:
1. Answer visitor questions accurately using the provided context
2. Be helpful, friendly, and professional
3. Identify potential leads and capture their contact information when appropriate
4. If someone shows buying intent or asks about pricing/services, use the capture_lead function

Guidelines:
- Always be conversational and natural
- Use the context provided to give accurate answers
- If you don't know something, say so politely
- When you sense someone is interested in the business/services, ask for their contact details
- For WhatsApp conversations, if someone types "TALK" or asks to speak with a human, inform them that someone will contact them shortly

Remember: You represent {client_name} and should maintain their brand voice and values."""

    def chat_with_context(
        self, 
        query: str, 
        context: List[str], 
        chat_history: List[Dict[str, str]], 
        system_prompt: str
    ) -> Dict[str, Any]:
        """
        Chat with LLM using RAG context and function calling for lead capture
        
        Returns:
        - {"type": "text", "content": "response text"} for normal responses
        - {"type": "function_call", "function": "capture_lead", "arguments": {...}} for lead capture
        """
        
        # Build plain context string for GeminiService
        context_text = "\n".join(context or [])

        # Use Gemini synchronously via asyncio runner
        try:
            ai_result = asyncio.run(self.gemini.generate_response(
                message=query,
                context=context_text,
                system_prompt=system_prompt,
                chat_history=chat_history
            ))
        except RuntimeError:
            # If there's already a running loop (rare here), create a new task
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                ai_result = loop.run_until_complete(self.gemini.generate_response(
                    message=query,
                    context=context_text,
                    system_prompt=system_prompt,
                    chat_history=chat_history
                ))
            finally:
                loop.close()

        # Map Gemini tool results to the legacy function_call shape when possible
        tool_results = ai_result.get("tool_results", {}) if isinstance(ai_result, dict) else {}
        if tool_results.get("contact_info"):
            args = tool_results["contact_info"]
            return {
                "type": "function_call",
                "function": "capture_lead",
                "arguments": {
                    "name": args.get("name", ""),
                    "email": args.get("email", ""),
                    "phone": args.get("phone", "")
                }
            }

        # Otherwise return a plain text response
        content = ai_result.get("response") if isinstance(ai_result, dict) else str(ai_result)
        if not content:
            content = "I'm sorry, I couldn't generate a response."
        return {"type": "text", "content": content}


# Global instance (kept for backward compatibility)
llm_service = LLMService()
