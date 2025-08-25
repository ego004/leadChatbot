import os
import logging
import json
import google.generativeai as genai
from typing import Dict, Any, List, Optional
from langchain.tools import BaseTool
from langchain.schema import BaseMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field
from app.config import settings

logger = logging.getLogger(__name__)


class LeadQualificationTool(BaseTool):
    """Tool for qualifying leads based on conversation"""
    name: str = "qualify_lead"
    description: str = "Determine if a user is a qualified lead based on their messages"
    
    def _run(self, user_message: str, conversation_context: str = "") -> str:
        """Qualify lead based on current user message only (not KB context).

        Rationale: KB may contain words like 'contact' which would inflate signals.
        """
        buying_signals = [
            "price", "cost", "pricing", "how much", "demo", "trial",
            "call", "meeting", "schedule", "interested", "tour", "book",
            "buy", "purchase", "sign up", "get started", "learn more"
        ]

        message_lower = user_message.lower()

        # If user shares contact info directly, consider them qualified
        import re
        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        phone_pattern = r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
        if re.search(email_pattern, user_message) or re.search(phone_pattern, user_message):
            return "QUALIFIED"

        signal_count = sum(1 for signal in buying_signals if signal in message_lower)

        if signal_count >= 2:
            return "QUALIFIED"
        elif signal_count >= 1:
            return "POTENTIAL"
        else:
            return "NOT_QUALIFIED"


class ContactCaptureTool(BaseTool):
    """Tool for capturing contact information from messages"""
    name: str = "capture_contact"
    description: str = "Extract contact information (name, email, phone) from user messages"
    
    def _run(self, message: str) -> Dict[str, str]:
        """Extract contact info from message with improved name handling."""
        import re

        result = {"name": "", "email": "", "phone": ""}

        # Email regex
        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        email_match = re.search(email_pattern, message)
        if email_match:
            result["email"] = email_match.group(0)

        # Phone regex (basic patterns, capture full match)
        phone_pattern = r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
        phone_match = re.search(phone_pattern, message)
        if phone_match:
            result["phone"] = phone_match.group(0)

        # Name extraction using intent phrases and allowing two-word names
        name_patterns = [
            r"\b(?:my\s+name\s+is|i\s+am|i'm|this\s+is|call\s+me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
        ]
        for pat in name_patterns:
            m = re.search(pat, message, flags=re.IGNORECASE)
            if m:
                # Use the captured name, preserve original casing of message slice
                result["name"] = m.group(1).strip().rstrip(".,!")
                break

        return result


class GeminiService:
    """Service for Google Gemini AI with LangChain tools"""
    
    def __init__(self):
        # Prefer settings, fall back to env var
        self.api_key = getattr(settings, "google_api_key", None) or os.getenv("GOOGLE_API_KEY")
        self.model_name = os.getenv("CHAT_MODEL_NAME", "gemma-3-27b-it")
        self.model = None
        # Online mode only if key present
        if self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                # Try requested model first
                try:
                    self.model = genai.GenerativeModel(self.model_name)
                except Exception as inner:
                    logger.warning(f"Model '{self.model_name}' init failed ({inner}); trying 'gemini-2.5-flash-lite'.")
                    self.model = genai.GenerativeModel('gemini-2.5-flash-lite')
            except Exception as e:
                logger.warning(f"Falling back to offline mode due to model init error: {e}")
        
        # Initialize tools
        self.tools = [
            LeadQualificationTool(),
            ContactCaptureTool()
        ]
    
    def get_tool_by_name(self, name: str) -> Optional[BaseTool]:
        """Get tool by name"""
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None
    
    async def generate_response(self, message: str, context: str, system_prompt: str = None, 
                               chat_history: List[Dict] = None) -> Dict[str, Any]:
        """Generate AI response using Gemini with tool calling capability"""
        
        try:
            # Build conversation context
            conversation: List[str] = []
            
            if context:
                conversation.append(f"Knowledge Base Context: {context}")
            
            if chat_history:
                for msg in chat_history[-5:]:  # Last 5 messages for context
                    sender = "Human" if msg.get("sender") == "user" else "Assistant"
                    conversation.append(f"{sender}: {msg.get('message', '')}")
            
            conversation.append(f"Human: {message}")
            
            # Compose full prompt with internal policy + user system prompt
            internal_policy = (
                "Internal policy (prepend to user system prompt):\n"
                "- Use the knowledge base verbatim; do not invent facts. If unsure, say so briefly.\n"
                "- Be strictly relevant: answer the user's question directly. Do NOT include unrelated details or large KB dumps (e.g., full hours/amenities/pricing lists) unless explicitly requested. Prefer concise summaries.\n"
                "- Tool usage is explicit. When qualifying or capturing contact details, emit a single line: 'TOOL_CALL: tool_name(arguments)'.\n"
                "- Lead qualification: generic pricing or basic questions = POTENTIAL (ask one helpful follow-up). Reserve QUALIFIED for explicit buying intent (demo/tour/signup/booking) or when contact details are shared.\n"
                "- If contact info is missing, gently ask once for email and phone. Mention the phone helps coordinate a quick tour. Keep it brief.\n"
                "- Keep tone friendly, concise, and proactive. Offer a tour when appropriate.\n"
            )
            user_prompt = system_prompt or "You are a helpful, friendly AI assistant. Answer naturally, be concise, and ask a clarifying question when needed."
            effective_system = f"{internal_policy}\n\nUser-provided system prompt:\n{user_prompt}"

            tool_block = (
                "You have access to the following tools:\n\n"
                "1. qualify_lead: Determine if the user is a qualified lead. Use without args, e.g.\n"
                "   TOOL_CALL: qualify_lead()\n"
                "   The system will compute QUALIFIED | POTENTIAL | NOT_QUALIFIED based on the current user message.\n\n"
                "2. capture_contact: Extract contact info. Supply JSON args exactly as a single-line call, e.g.\n"
                "   TOOL_CALL: capture_contact({\"name\":\"Alex Chen\",\"email\":\"alex@example.com\",\"phone\":\"415-555-1212\"})\n"
                "   Only include fields you are confident about; leave others as empty strings.\n\n"
                "General rule: Emit a single line exactly as:\n"
                "TOOL_CALL: tool_name(arguments)\n"
            )
            full_prompt = f"""
SYSTEM INSTRUCTIONS:\n{effective_system}

TOOLS:\n{tool_block}

CONVERSATION:\n{chr(10).join(conversation)}
"""
            
            # If online model is not available, produce an offline, context-aware response
            if not self.model:
                offline_resp = self._offline_response(message, context, system_prompt)
                return offline_resp

            # Generate response via Gemini API
            try:
                response = self.model.generate_content(full_prompt)
                response_text = response.text
                
                # Check for tool calls
                tool_results = {}
                if "TOOL_CALL:" in response_text:
                    lines = response_text.split('\n')
                    clean_response_lines = []
                    
                    for line in lines:
                        if line.strip().startswith("TOOL_CALL:"):
                            # Parse tool call
                            tool_call = line.replace("TOOL_CALL:", "").strip()
                            tool_results.update(self._execute_tool_call(tool_call, message, context))
                        else:
                            clean_response_lines.append(line)
                    
                    response_text = '\n'.join(clean_response_lines).strip()

                # Fallback: if model only produced tool calls, provide a concise reply
                if not response_text.strip():
                    if tool_results.get("contact_info"):
                        ci = tool_results["contact_info"]
                        name = (ci.get("name") or "").strip()
                        response_text = (
                            f"Thanks{', ' + name if name else ''}. I've saved your contact info. "
                            "Would you like to book a quick tour?"
                        )
                    elif tool_results.get("lead_qualification") == "POTENTIAL":
                        response_text = (
                            "Happy to help! Would you like pricing details emailed to you? "
                            "What's the best email and phone to coordinate a quick tour?"
                        )
                    else:
                        response_text = "How else can I help?"
                
                return {
                    "response": response_text,
                    "tool_results": tool_results,
                    "has_tools": len(tool_results) > 0
                }
                
            except Exception as e:
                logger.error(f"Error generating response from Gemini: {e}")
                return {
                    "response": "I'm sorry, but I encountered an error. Please try again later.",
                    "tool_results": {},
                    "has_tools": False
                }
        
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return {
                "response": "I'm sorry, I'm having trouble processing your request right now. Please try again later.",
                "tool_results": {},
                "has_tools": False
            }
    
    def _execute_tool_call(self, tool_call: str, message: str, context: str) -> Dict[str, Any]:
        """Execute a tool call and return results"""
        try:
            # Normalize whitespace
            call = tool_call.strip()
            
            if call.startswith("qualify_lead("):
                tool = self.get_tool_by_name("qualify_lead")
                if tool:
                    result = tool._run(message, context)
                    return {"lead_qualification": result}
            
            if call.startswith("capture_contact("):
                # LLM-first parsing: expect JSON args inside parentheses
                try:
                    args_str = call[len("capture_contact("):-1].strip()  # remove trailing ')'
                    parsed = json.loads(args_str) if args_str else {}
                    # Sanitize and coerce to expected shape
                    name = (parsed.get("name") or "").strip()
                    email = (parsed.get("email") or "").strip()
                    phone = (parsed.get("phone") or "").strip()
                    return {"contact_info": {"name": name, "email": email, "phone": phone}}
                except Exception:
                    # Fallback to regex tool extraction
                    tool = self.get_tool_by_name("capture_contact")
                    if tool:
                        result = tool._run(message)
                        return {"contact_info": result}
            
            return {}
            
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return {}

    def _offline_response(self, message: str, context: str, system_prompt: Optional[str]) -> Dict[str, Any]:
        """Deterministic offline response using simple heuristics. Avoids external API for tests/dev."""
        try:
            # Use top 1-2 lines of context for echo; if no context, generic reply
            ctx = (context or "").strip()
            ctx_lines = [l.strip() for l in ctx.splitlines() if l.strip()]
            snippet = " ".join(ctx_lines[:2]) if ctx_lines else ""

            # Heuristic tool execution (no model parsing)
            tool_results = {}
            # Qualify lead
            try:
                qual = self.get_tool_by_name("qualify_lead")
                if qual:
                    tool_results["lead_qualification"] = qual._run(message, ctx)
            except Exception:
                pass
            # Capture contact
            try:
                cap = self.get_tool_by_name("capture_contact")
                if cap:
                    tool_results["contact_info"] = cap._run(message)
            except Exception:
                pass

            base_response = ""
            if snippet:
                base_response = f"According to the knowledge base: {snippet}"
            else:
                base_response = "How can I help you today?"

            # Slightly tailor with the user message
            final = f"{base_response}\n\nYou asked: {message}"
            return {"response": final, "tool_results": tool_results, "has_tools": len(tool_results) > 0}
        except Exception as e:
            logger.error(f"Offline response error: {e}")
            return {"response": "I'm sorry, I'm having trouble right now.", "tool_results": {}, "has_tools": False}
    
    async def generate_simple_response(self, prompt: str) -> str:
        """Generate simple response for utility functions"""
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return "Error"
