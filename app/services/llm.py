import openai
from typing import Dict, Any, Optional, List
import json
from app.config import settings

openai.api_key = settings.openai_api_key


class LLMService:
    def __init__(self):
        self.client = openai.OpenAI(api_key=settings.openai_api_key)
    
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
        
        # Prepare context
        context_text = "\n\n".join(context) if context else "No specific context available."
        
        # Prepare chat history
        messages = [
            {
                "role": "system", 
                "content": f"{system_prompt}\n\nContext from knowledge base:\n{context_text}"
            }
        ]
        
        # Add chat history
        for msg in chat_history[-10:]:  # Last 10 messages for context
            messages.append({
                "role": "user" if msg["sender"] == "user" else "assistant",
                "content": msg["message"]
            })
        
        # Add current query
        messages.append({"role": "user", "content": query})
        
        # Define the lead capture function
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "capture_lead",
                    "description": "Capture lead information when a visitor shows interest or provides contact details",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "The lead's name"
                            },
                            "email": {
                                "type": "string",
                                "description": "The lead's email address"
                            },
                            "phone": {
                                "type": "string",
                                "description": "The lead's phone number (optional)"
                            }
                        },
                        "required": ["name", "email"]
                    }
                }
            }
        ]
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.7,
                max_tokens=500
            )
            
            message = response.choices[0].message
            
            # Check if it's a function call
            if message.tool_calls:
                tool_call = message.tool_calls[0]
                if tool_call.function.name == "capture_lead":
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                        return {
                            "type": "function_call",
                            "function": "capture_lead",
                            "arguments": arguments
                        }
                    except json.JSONDecodeError:
                        # Fallback to text response if JSON parsing fails
                        pass
            
            # Regular text response
            return {
                "type": "text",
                "content": message.content or "I'm sorry, I couldn't generate a response."
            }
            
        except Exception as e:
            print(f"LLM Error: {e}")
            return {
                "type": "text",
                "content": "I'm experiencing some technical difficulties. Please try again in a moment."
            }


# Global instance
llm_service = LLMService()
