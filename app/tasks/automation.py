from celery import Celery
from sqlalchemy.orm import Session
from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.lead import Lead
from app.models.automation import Sequence, SequenceStep, LeadSequenceState, SequenceType, SequenceStatus
from datetime import datetime, timedelta
from app.services.email_chat_service import EmailChatService


def get_db_session():
    """Get database session for Celery tasks"""
    return SessionLocal()


@celery_app.task(bind=True)
def task_enroll_lead(self, lead_id: str, sequence_type: str = "email"):
    """Enroll a lead in an automation sequence"""
    db = get_db_session()
    try:
        lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()
        if not lead:
            raise Exception(f"Lead {lead_id} not found")
        
        sequence = db.query(Sequence).filter(
            Sequence.client_id == lead.client_id,
            Sequence.type == SequenceType(sequence_type)
        ).first()
        
        if not sequence:
            print(f"No {sequence_type} sequence found for client {lead.client_id}")
            return
        
        existing_state = db.query(LeadSequenceState).filter(
            LeadSequenceState.lead_id == lead_id,
            LeadSequenceState.sequence_id == sequence.sequence_id
        ).first()
        
        if existing_state:
            print(f"Lead {lead_id} already enrolled in sequence {sequence.sequence_id}")
            return
        
        first_step = db.query(SequenceStep).filter(
            SequenceStep.sequence_id == sequence.sequence_id
        ).order_by(SequenceStep.step_number).first()
        
        if not first_step:
            print(f"No steps found for sequence {sequence.sequence_id}")
            return
        
        lead_state = LeadSequenceState(
            lead_id=lead_id,
            sequence_id=sequence.sequence_id,
            current_step_id=first_step.step_id,
            status=SequenceStatus.ACTIVE,
            next_send_time=datetime.utcnow() + timedelta(hours=first_step.delay_in_hours)
        )
        
        db.add(lead_state)
        db.commit()
        print(f"Lead {lead_id} enrolled in {sequence_type} sequence")
        
    except Exception as e:
        print(f"Error enrolling lead {lead_id}: {e}")
        raise e
    finally:
        db.close()


@celery_app.task(bind=True)
def task_process_follow_ups(self):
    """Process scheduled follow-up messages (runs periodically)"""
    db = get_db_session()
    email_chat_service = EmailChatService(db)
    try:
        current_time = datetime.utcnow()
        ready_states = db.query(LeadSequenceState).filter(
            LeadSequenceState.status == SequenceStatus.ACTIVE,
            LeadSequenceState.next_send_time <= current_time
        ).all()
        
        for state in ready_states:
            try:
                lead = db.query(Lead).filter(Lead.lead_id == state.lead_id).first()
                sequence = db.query(Sequence).filter(Sequence.sequence_id == state.sequence_id).first()
                current_step = db.query(SequenceStep).filter(SequenceStep.step_id == state.current_step_id).first()
                
                if not all([lead, sequence, current_step]) or lead.email_manual_override:
                    continue
                
                if sequence.type == SequenceType.EMAIL:
                    success = send_email(email_chat_service, lead, current_step.template_body)
                else:
                    success = False
                
                if success:
                    next_step = db.query(SequenceStep).filter(
                        SequenceStep.sequence_id == sequence.sequence_id,
                        SequenceStep.step_number > current_step.step_number
                    ).order_by(SequenceStep.step_number).first()
                    
                    if next_step:
                        state.current_step_id = next_step.step_id
                        state.next_send_time = current_time + timedelta(hours=next_step.delay_in_hours)
                    else:
                        state.status = SequenceStatus.COMPLETED
                        state.next_send_time = None
                    
                    db.commit()
                    
            except Exception as e:
                print(f"Error processing follow-up for lead {state.lead_id}: {e}")
                continue
        
    except Exception as e:
        print(f"Error in task_process_follow_ups: {e}")
    finally:
        db.close()


def send_email(email_service: EmailChatService, lead: Lead, template_body: str) -> bool:
    """Send automated follow-up email to a lead"""
    try:
        message_body = template_body.replace("{name}", lead.name or "there")
        message_body = message_body.replace("{email}", lead.email)
        
        # Use the email service to send the email
        result = email_service.send_auto_response(
            to_email=lead.email,
            subject="Following Up",
            message=message_body,
            lead_id=str(lead.lead_id),
            client_id=str(lead.client_id),
            original_message_id=""
        )
        
        return result.get("success", False)
        
    except Exception as e:
        print(f"Error sending email to {lead.email}: {e}")
        return False


# Configure periodic task
from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    'process-follow-ups': {
        'task': 'app.tasks.automation.task_process_follow_ups',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
}
celery_app.conf.timezone = 'UTC'
