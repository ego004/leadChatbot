import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.services.lead_service import LeadService
from app.models.lead import EmailMessage
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """Service for email automation and follow-ups"""
    
    def __init__(self, db: Session):
        self.db = db
        self.lead_service = LeadService(db)
        
        # Email configuration
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.email_user = os.getenv("EMAIL_USER")
        self.email_password = os.getenv("EMAIL_PASSWORD")
        self.from_name = os.getenv("EMAIL_FROM_NAME", "LeadGenius AI")

    def _resolve_email_config(self, client_id: str) -> dict:
        """Return effective SMTP config for a client, falling back to globals."""
        try:
            from app.models.client import Client
            client = self.db.query(Client).filter(Client.client_id == client_id).first()
        except Exception:
            client = None

        # Prefer per-client values when set
        smtp_server = (client.smtp_server if client and client.smtp_server else self.smtp_server)
        smtp_port = (client.smtp_port if client and client.smtp_port else self.smtp_port)
        smtp_user = (client.smtp_user if client and client.smtp_user else self.email_user)
        smtp_password = (client.smtp_password if client and client.smtp_password else self.email_password)
        from_name = (client.smtp_from_name if client and client.smtp_from_name else self.from_name)

        # email_enabled: if explicitly False, disable; if None, treat as enabled
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
        }

    def is_configured(self, client_id: str | None = None) -> bool:
        """Check if email is properly configured (global or per client)."""
        if client_id:
            cfg = self._resolve_email_config(client_id)
            return bool(cfg.get("enabled"))
        return bool(self.email_user and self.email_password)
    
    def send_email(self, to_email: str, subject: str, message: str, lead_id: str, 
                   client_id: str, html_content: str = None) -> Dict[str, Any]:
        """Send email with chat history context"""
        
        cfg = self._resolve_email_config(client_id)
        if not cfg.get("enabled"):
            logger.error("Email not configured")
            return {"success": False, "error": "Email not configured"}
        
        # Create email message record with context
        email_msg = self.lead_service.create_email_message(
            lead_id=lead_id,
            client_id=client_id,
            subject=subject,
            message_text=message,
            is_outbound=True,
            include_context=True
        )
        
        try:
            # Create email
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{cfg['from_name']} <{cfg['smtp_user']}>"
            msg['To'] = to_email
            
            # Add text content
            text_part = MIMEText(message, 'plain')
            msg.attach(text_part)
            
            # Add HTML content if provided
            if html_content:
                html_part = MIMEText(html_content, 'html')
                msg.attach(html_part)
            
            # Send email
            with smtplib.SMTP(cfg['smtp_server'], cfg['smtp_port']) as server:
                server.starttls()
                server.login(cfg['smtp_user'], cfg['smtp_password'])
                server.send_message(msg)
            
            # Update message status
            email_msg.status = "sent"
            self.db.commit()
            
            logger.info(f"Email sent successfully to {to_email}")
            return {"success": True, "message_id": str(email_msg.message_id)}
            
        except Exception as e:
            # Update message status to failed
            email_msg.status = "failed"
            self.db.commit()
            
            logger.error(f"Failed to send email: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def send_follow_up_email(self, lead_id: str, client_id: str, 
                            custom_subject: str = None, custom_message: str = None) -> Dict[str, Any]:
        """Send follow-up email with chat context"""
        
        # Get lead details
        lead_data = self.lead_service.get_lead_with_email_history(lead_id)
        if not lead_data or not lead_data["lead"].email:
            return {"success": False, "error": "Lead not found or no email address"}
        
        lead = lead_data["lead"]
        
        # Check if manual override is enabled
        if lead.email_manual_override:
            return {"success": False, "error": "Manual override enabled for this lead"}
        
        # Generate contextual follow-up email
        if custom_subject and custom_message:
            subject = custom_subject
            message = custom_message
        else:
            chat_context = lead_data["chat_context"]
            subject, message = self._generate_follow_up_email(lead, chat_context)
        
        # Create HTML version
        html_content = self._create_html_email(message, lead.name or "there")
        
        return self.send_email(
            to_email=lead.email,
            subject=subject,
            message=message,
            lead_id=lead_id,
            client_id=client_id,
            html_content=html_content
        )
    
    def _generate_follow_up_email(self, lead, chat_context: str) -> tuple[str, str]:
        """Generate contextual follow-up email based on chat history"""
        
        name = lead.name or "there"
        
        if "pricing" in chat_context.lower() or "cost" in chat_context.lower():
            subject = "Pricing Information You Requested"
            message = f"""Hi {name},

I noticed you were asking about our pricing during your visit to our website. I'd be happy to discuss our packages and find the best fit for your needs.

Our solutions are designed to provide excellent value, and we offer flexible pricing options to match different requirements.

Would you like to schedule a quick 15-minute call to discuss your specific needs and how we can help?

Best regards,
The Team"""
        
        elif "demo" in chat_context.lower() or "trial" in chat_context.lower():
            subject = "Your Demo Request - Let's Get Started!"
            message = f"""Hi {name},

Thanks for your interest in seeing our solution in action! I can set up a personalized demo that shows exactly how our platform can benefit your business.

The demo typically takes about 20 minutes and covers:
- Key features relevant to your needs
- Real-world use cases
- Implementation process
- Q&A session

What's your availability this week for a demo?

Best regards,
The Team"""
        
        elif "feature" in chat_context.lower() or "how does" in chat_context.lower():
            subject = "Answers to Your Questions About Our Features"
            message = f"""Hi {name},

I saw you had questions about our features during your website visit. I'd love to provide you with detailed answers and show you exactly how our solution works.

Our platform offers comprehensive capabilities, and I can walk you through the specific features that would be most valuable for your use case.

Are you available for a brief call this week to discuss your questions?

Best regards,
The Team"""
        
        else:
            subject = "Following Up on Your Interest"
            message = f"""Hi {name},

Thanks for visiting our website and exploring our solutions. I wanted to personally follow up to see if you have any questions about how we can help achieve your goals.

Many of our clients find it helpful to have a brief conversation to understand their specific needs and how our platform can address them.

Would you be interested in a quick 15-minute call to discuss your requirements?

Best regards,
The Team"""
        
        return subject, message
    
    def _create_html_email(self, text_content: str, name: str) -> str:
        """Create HTML version of email"""
        
        html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Follow Up</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
        <h2 style="color: #2c3e50; margin-top: 0;">Hello {name}!</h2>
    </div>
    
    <div style="background-color: white; padding: 20px; border-radius: 8px; border: 1px solid #e9ecef;">
        {text_content.replace(chr(10), '<br>')}
    </div>
    
    <div style="margin-top: 20px; padding: 15px; background-color: #e8f4f8; border-radius: 8px; text-align: center;">
        <p style="margin: 0; font-size: 14px; color: #666;">
            This email was sent because you interacted with our website chatbot. 
            If you'd prefer not to receive follow-up emails, please let us know.
        </p>
    </div>
</body>
</html>
"""
        return html_template
    
    def handle_incoming_email(self, from_email: str, subject: str, message: str) -> Dict[str, Any]:
        """Handle incoming email responses and pause automation"""
        
        try:
            # Find lead by email across all clients
            from app.models.lead import Lead
            lead = self.db.query(Lead).filter(Lead.email == from_email).first()
            
            if not lead:
                logger.warning(f"Received email from unknown address: {from_email}")
                return {"success": False, "error": "Lead not found"}
            
            # Create incoming email record
            email_msg = EmailMessage(
                lead_id=str(lead.lead_id),
                client_id=str(lead.client_id),
                subject=f"Re: {subject}",
                message_text=message,
                is_outbound=False,
                status="received"
            )
            
            self.db.add(email_msg)
            
            # Enable manual override to pause automation
            lead.email_manual_override = True
            lead.status = "contacted"  # Update status since they responded
            
            self.db.commit()
            
            logger.info(f"Incoming email processed for lead {lead.lead_id}")
            return {
                "success": True, 
                "lead_id": str(lead.lead_id),
                "message": "Manual override enabled, automation paused"
            }
            
        except Exception as e:
            logger.error(f"Error handling incoming email: {str(e)}")
            return {"success": False, "error": str(e)}
    
    def resume_automation(self, lead_id: str) -> Dict[str, Any]:
        """Resume automation for a lead (disable manual override)"""
        
        lead = self.lead_service.set_email_manual_override(lead_id, False)
        if lead:
            return {"success": True, "message": "Email automation resumed"}
        else:
            return {"success": False, "error": "Lead not found"}
