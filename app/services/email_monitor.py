import asyncio
import logging
from app.services.email_chat_service import EmailChatService
from app.database import get_db
from app.models.client import Client

logger = logging.getLogger(__name__)


class EmailMonitor:
    """Background service to monitor and process incoming emails"""
    
    def __init__(self):
        self.running = False
        self.task = None
    
    async def start(self):
        """Start the email monitoring service"""
        if self.running:
            logger.info("Email monitor already running")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._monitor_loop())
        logger.info("Email monitor started")
    
    async def stop(self):
        """Stop the email monitoring service"""
        if not self.running:
            return
        
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        logger.info("Email monitor stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            try:
                # Get database session
                db = next(get_db())
                
                # Create email chat service
                email_chat_service = EmailChatService(db)

                processed_any = False
                # Iterate all clients and process per-client inboxes
                clients = db.query(Client).all()
                for c in clients:
                    try:
                        if email_chat_service.is_configured(str(c.client_id)):
                            email_chat_service.check_and_process_emails(str(c.client_id))
                            processed_any = True
                    except Exception as ce:
                        logger.error(f"Error monitoring client {c.client_id}: {ce}")

                # If none processed via per-client, try global config once
                if not processed_any and email_chat_service.is_configured(None):
                    email_chat_service.check_and_process_emails(None)
                
                # Wait before next check
                await asyncio.sleep(60)  # Check every minute
                
            except Exception as e:
                logger.error(f"Error in email monitoring loop: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes on error
            finally:
                if 'db' in locals():
                    db.close()


# Global email monitor instance
email_monitor = EmailMonitor()


async def start_email_monitoring():
    """Start email monitoring service"""
    await email_monitor.start()


async def stop_email_monitoring():
    """Stop email monitoring service"""
    await email_monitor.stop()
