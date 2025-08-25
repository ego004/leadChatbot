import os
import asyncio
import imaplib
import email
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from typing import Optional, Dict, Any, List
from datetime import timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.services.lead_service import LeadService
from app.services.gemini_service import GeminiService
from app.services.vector_store_service import VectorStoreService
from app.models.lead import EmailMessage, Lead
from app.models.knowledge_base import ClientDeployment
import logging
import re
import threading
import time

logger = logging.getLogger(__name__)


class EmailChatService:
    """Service for automatic email chatting with manual override"""
    
    def __init__(self, db: Session):
        self.db = db
        self.lead_service = LeadService(db)
        self.gemini_service = GeminiService()
        # Vector store is selected per-client via VectorStoreService (Supabase preferred, Chroma fallback)
        
        # Email configuration
        self.imap_server = os.getenv("IMAP_SERVER", "imap.gmail.com")
        self.imap_port = int(os.getenv("IMAP_PORT", "993"))
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.email_user = os.getenv("EMAIL_USER")
        self.email_password = os.getenv("EMAIL_PASSWORD")
        self.from_name = os.getenv("EMAIL_FROM_NAME", "LeadGenius AI")
        
        # Auto-response settings
        self.auto_response_enabled = os.getenv("AUTO_EMAIL_RESPONSE", "true").lower() == "true"
        self.response_delay = int(os.getenv("EMAIL_RESPONSE_DELAY", "30"))  # seconds
        
    def _resolve_email_config(self, client_id: str | None) -> dict:
        """Return effective IMAP/SMTP config for a client, falling back to globals."""
        client = None
        if client_id:
            try:
                from app.models.client import Client
                client = self.db.query(Client).filter(Client.client_id == client_id).first()
            except Exception:
                client = None

        smtp_server = (client.smtp_server if client and client.smtp_server else self.smtp_server)
        smtp_port = (client.smtp_port if client and client.smtp_port else self.smtp_port)
        smtp_user = (client.smtp_user if client and client.smtp_user else self.email_user)
        smtp_password = (client.smtp_password if client and client.smtp_password else self.email_password)
        from_name = (client.smtp_from_name if client and client.smtp_from_name else self.from_name)
        imap_server = (client.imap_server if client and client.imap_server else self.imap_server)
        imap_port = (client.imap_port if client and client.imap_port else self.imap_port)

        if client and client.email_enabled is False:
            return {"enabled": False}

        enabled = bool(smtp_user and smtp_password)
        return {
            "enabled": enabled,
            "smtp_server": smtp_server,
            "smtp_port": int(smtp_port) if smtp_port else 587,
            "smtp_user": smtp_user,
            "smtp_password": smtp_password,
            "from_name": from_name,
            "imap_server": imap_server,
            "imap_port": int(imap_port) if imap_port else 993,
        }

    def is_configured(self, client_id: str | None = None) -> bool:
        """Check if email is properly configured (global or per client)."""
        cfg = self._resolve_email_config(client_id)
        return bool(cfg.get("enabled"))
    
    def start_email_monitoring(self):
        """Start monitoring emails in a background thread"""
        if not self.is_configured():
            logger.error("Email not configured for monitoring")
            return
        
        def monitor_emails():
            while True:
                try:
                    self.check_and_process_emails()
                    time.sleep(60)  # Check every minute
                except Exception as e:
                    logger.error(f"Error in email monitoring: {e}")
                    time.sleep(300)  # Wait 5 minutes on error
        
        thread = threading.Thread(target=monitor_emails, daemon=True)
        thread.start()
        logger.info("Email monitoring started")
    
    def check_and_process_emails(self, client_id: str | None = None):
        """Check for new emails and process them. If client_id is provided, use that client's mailbox."""
        try:
            cfg = self._resolve_email_config(client_id)
            if not cfg.get("enabled"):
                logger.warning("Email not configured, skipping monitoring cycle")
                return
            # Connect to IMAP server for this client/global
            mail = imaplib.IMAP4_SSL(cfg['imap_server'], cfg['imap_port'])
            mail.login(cfg['smtp_user'], cfg['smtp_password'])
            mail.select('inbox')
            
            # Search for unread emails
            status, messages = mail.search(None, 'UNSEEN')
            email_ids = messages[0].split()
            
            for email_id in email_ids:
                try:
                    # Fetch email
                    status, msg_data = mail.fetch(email_id, '(RFC822)')
                    email_body = msg_data[0][1]
                    email_message = email.message_from_bytes(email_body)
                    
                    # Process the email
                    self.process_incoming_email(email_message, client_id=client_id)
                    
                except Exception as e:
                    logger.error(f"Error processing email {email_id}: {e}")
            
            mail.close()
            mail.logout()
            
        except Exception as e:
            logger.error(f"Error checking emails: {e}")
    
    def process_incoming_email(self, email_message, client_id: str | None = None):
        """Process a single incoming email"""
        try:
            # Extract email details
            from_email = email_message['From']
            subject = email_message['Subject']
            
            # Clean email address
            from_email = re.search(r'[\w\.-]+@[\w\.-]+', from_email).group() if from_email else None
            
            if not from_email:
                return
            
            # Decode subject
            if subject:
                decoded_subject = decode_header(subject)[0]
                if isinstance(decoded_subject[0], bytes):
                    subject = decoded_subject[0].decode(decoded_subject[1] or 'utf-8')
                else:
                    subject = decoded_subject[0]
            
            # Extract email body
            body = self.extract_email_body(email_message)
            
            if not body:
                return
            
            # Find lead by email (prefer same client when provided)
            if client_id:
                lead = self.db.query(Lead).filter(Lead.email == from_email, Lead.client_id == client_id).first()
            else:
                lead = self.db.query(Lead).filter(Lead.email == from_email).first()
            
            if not lead:
                logger.info(f"Received email from unknown address: {from_email}")
                return
            
            # Check if manual override is enabled
            if lead.email_manual_override:
                logger.info(f"Manual override enabled for lead {lead.lead_id}, skipping auto-response")
                # Still save the incoming email
                self.save_incoming_email(lead, subject, body)
                return
            
            # Save incoming email
            incoming_msg = self.save_incoming_email(lead, subject, body)
            
            # Generate and send auto-response if enabled
            if self.auto_response_enabled:
                # Add delay to seem more human
                time.sleep(self.response_delay)
                self.generate_and_send_response(lead, subject, body, incoming_msg)
            
        except Exception as e:
            logger.error(f"Error processing incoming email: {e}")
    
    def extract_email_body(self, email_message) -> str:
        """Extract text body from email message"""
        body = ""
        
        if email_message.is_multipart():
            for part in email_message.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        body = part.get_payload(decode=True).decode()
                        break
                    except:
                        continue
        else:
            try:
                body = email_message.get_payload(decode=True).decode()
            except:
                body = str(email_message.get_payload())
        
        # Clean up the body (remove quoted text, signatures, etc.)
        body = self.clean_email_body(body)
        return body
    
    def clean_email_body(self, body: str) -> str:
        """Clean email body by removing quoted text and signatures"""
        lines = body.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
            
            # Stop at common reply indicators
            if any(indicator in line.lower() for indicator in [
                'on ', 'wrote:', '-----original message-----', 
                'from:', 'sent:', 'to:', 'subject:', '>'
            ]):
                break
            
            # Skip signature lines
            if line.startswith('--') or 'best regards' in line.lower() or 'sincerely' in line.lower():
                break
            
            cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines).strip()
    
    def save_incoming_email(self, lead: Lead, subject: str, body: str) -> EmailMessage:
        """Save incoming email to database"""
        email_msg = EmailMessage(
            lead_id=str(lead.lead_id),
            client_id=str(lead.client_id),
            subject=subject or "No Subject",
            message_text=body,
            is_outbound=False,
            status="received"
        )
        
        self.db.add(email_msg)
        self.db.commit()
        self.db.refresh(email_msg)
        
        logger.info(f"Saved incoming email from {lead.email}")
        return email_msg
    
    def generate_and_send_response(self, lead: Lead, original_subject: str, 
                                 original_body: str, incoming_msg: EmailMessage):
        """Generate AI response and send email"""
        try:
            # Get client deployment for system prompt
            deployment = self.db.query(ClientDeployment).filter(
                ClientDeployment.client_id == lead.client_id
            ).first()
            
            # Get knowledge base context
            vs = VectorStoreService(collection_name=f"client_{lead.client_id}")
            docs = vs.query(original_body, k=5)
            context = "\n".join([d.page_content for d in docs])
            
            # Get email conversation history
            email_history = self.get_email_conversation_history(lead.lead_id)
            
            # Generate response using Gemini
            system_prompt = self.build_email_system_prompt(deployment, lead)
            
            # Run async Gemini call from sync context
            ai_result = self._run_async(
                self.gemini_service.generate_response(
                    message=original_body,
                    context=context,
                    system_prompt=system_prompt,
                    chat_history=email_history
                )
            )
            
            response_text = ai_result["response"]
            
            # Generate response subject
            if original_subject.lower().startswith('re:'):
                response_subject = original_subject
            else:
                response_subject = f"Re: {original_subject}"
            
            # Send response email
            result = self.send_auto_response(
                to_email=lead.email,
                subject=response_subject,
                message=response_text,
                lead_id=str(lead.lead_id),
                client_id=str(lead.client_id),
                original_message_id=str(incoming_msg.message_id)
            )
            
            if result["success"]:
                logger.info(f"Auto-response sent to {lead.email}")
            else:
                logger.error(f"Failed to send auto-response: {result['error']}")
                
        except Exception as e:
            logger.error(f"Error generating response: {e}")
    
    def build_email_system_prompt(self, deployment: ClientDeployment, lead: Lead) -> str:
        """Build system prompt for email responses"""
        # Prefer email-specific prompt, fallback to website prompt, then default
        if deployment and getattr(deployment, "email_system_prompt", None):
            base_prompt = deployment.email_system_prompt
        elif deployment and getattr(deployment, "website_system_prompt", None):
            base_prompt = deployment.website_system_prompt
        else:
            base_prompt = "You are a helpful AI assistant."
        
        welcome_hint = ""
        if deployment and getattr(deployment, "email_welcome_message", None):
            welcome_hint = f"\nFirst-reply guidance: If this is your first reply in the thread and a friendly greeting is appropriate, begin with: \"{deployment.email_welcome_message}\"\n"

        email_prompt = f"""
{base_prompt}

You are responding to an email from a potential customer. Here are important guidelines:

1. Be professional and helpful
2. Keep responses concise but informative
3. Always try to move the conversation forward
4. If they ask questions you can't answer from the knowledge base, offer to connect them with a human
5. Use a friendly, conversational tone
6. Sign emails as "The Team" or use the company name
7. Don't mention that you're an AI unless specifically asked

Customer Information:
- Name: {lead.name or 'Valued Customer'}
- Email: {lead.email}
- Status: {lead.status.value if lead.status else 'New'}

{welcome_hint}

Respond naturally as if you're a helpful team member following up on their inquiry.
"""
        return email_prompt
    
    def get_email_conversation_history(self, lead_id: str, limit: int = 10) -> List[Dict]:
        """Get recent email conversation history"""
        messages = self.db.query(EmailMessage).filter(
            EmailMessage.lead_id == lead_id
        ).order_by(EmailMessage.created_at.desc()).limit(limit).all()
        
        history = []
        for msg in reversed(messages):
            sender = "user" if not msg.is_outbound else "assistant"
            history.append({
                "sender": sender,
                "message": f"Subject: {msg.subject}\n\n{msg.message_text}"
            })
        
        return history
    
    def send_auto_response(self, to_email: str, subject: str, message: str, 
                          lead_id: str, client_id: str, original_message_id: str) -> Dict[str, Any]:
        """Send automatic email response"""
        try:
            # Create email message record
            email_msg = EmailMessage(
                lead_id=lead_id,
                client_id=client_id,
                subject=subject,
                message_text=message,
                is_outbound=True,
                status="pending"
            )
            
            self.db.add(email_msg)
            self.db.commit()
            self.db.refresh(email_msg)
            
            # Create and send email
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            cfg = self._resolve_email_config(client_id)
            if not cfg.get("enabled"):
                raise RuntimeError("Email not configured for client")
            msg['From'] = f"{cfg['from_name']} <{cfg['smtp_user']}>"
            msg['To'] = to_email
            msg['In-Reply-To'] = original_message_id
            msg['References'] = original_message_id
            
            # Add text content
            text_part = MIMEText(message, 'plain')
            msg.attach(text_part)
            
            # Add HTML content
            html_content = self.create_html_email_response(message)
            html_part = MIMEText(html_content, 'html')
            msg.attach(html_part)
            
            # Send email
            with smtplib.SMTP(cfg['smtp_server'], cfg['smtp_port']) as server:
                server.starttls()
                server.login(cfg['smtp_user'], cfg['smtp_password'])
                server.send_message(msg)
            
            # Update status
            email_msg.status = "sent"
            self.db.commit()
            
            return {"success": True, "message_id": str(email_msg.message_id)}
            
        except Exception as e:
            if 'email_msg' in locals():
                email_msg.status = "failed"
                self.db.commit()
            
            logger.error(f"Failed to send auto-response: {e}")
            return {"success": False, "error": str(e)}
    
    def create_html_email_response(self, text_content: str) -> str:
        """Create HTML version of auto-response email"""
        html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Response</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background-color: white; padding: 20px; border-radius: 8px;">
        {text_content.replace(chr(10), '<br>')}
    </div>
    
    <div style="margin-top: 20px; padding: 15px; background-color: #f8f9fa; border-radius: 8px; text-align: center;">
        <p style="margin: 0; font-size: 12px; color: #666;">
            This is an automated response. If you need immediate assistance, please let us know.
        </p>
    </div>
</body>
</html>
"""
        return html_template

    # Internal helpers
    def _run_async(self, coro):
        """Run an async coroutine from a sync context safely."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Running inside an event loop (e.g., FastAPI). Use a new loop.
                new_loop = asyncio.new_event_loop()
                try:
                    return new_loop.run_until_complete(coro)
                finally:
                    new_loop.close()
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            # No event loop; create one
            return asyncio.run(coro)
    
    def enable_manual_override(self, lead_id: str) -> Dict[str, Any]:
        """Enable manual override for email conversations"""
        lead = self.db.query(Lead).filter(Lead.lead_id == lead_id).first()
        if lead:
            lead.email_manual_override = True
            self.db.commit()
            logger.info(f"Manual override enabled for lead {lead_id}")
            return {"success": True, "message": "Manual override enabled"}
        return {"success": False, "error": "Lead not found"}
    
    def disable_manual_override(self, lead_id: str) -> Dict[str, Any]:
        """Disable manual override and resume auto-responses"""
        lead = self.db.query(Lead).filter(Lead.lead_id == lead_id).first()
        if lead:
            lead.email_manual_override = False
            self.db.commit()
            logger.info(f"Manual override disabled for lead {lead_id}")
            return {"success": True, "message": "Auto-responses resumed"}
        return {"success": False, "error": "Lead not found"}
    
    def get_email_conversations(self, client_id: str, active_only: bool = True) -> List[Dict]:
        """Get all email conversations for monitoring"""
        query = self.db.query(Lead).filter(Lead.client_id == client_id)
        
        if active_only:
            # Only leads with recent email activity
            query = query.join(EmailMessage).filter(
                EmailMessage.created_at >= func.now() - timedelta(days=7)
            )
        
        leads = query.all()
        conversations = []
        
        for lead in leads:
            recent_messages = self.db.query(EmailMessage).filter(
                EmailMessage.lead_id == lead.lead_id
            ).order_by(EmailMessage.created_at.desc()).limit(5).all()
            
            if recent_messages:
                conversations.append({
                    "lead_id": str(lead.lead_id),
                    "lead_email": lead.email,
                    "lead_name": lead.name,
                    "manual_override": lead.email_manual_override,
                    "last_message": {
                        "subject": recent_messages[0].subject,
                        "preview": recent_messages[0].message_text[:100] + "...",
                        "is_outbound": recent_messages[0].is_outbound,
                        "created_at": recent_messages[0].created_at
                    },
                    "message_count": len(recent_messages)
                })
        
        return conversations
