from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,      # validate connections before using
    pool_recycle=1800,       # recycle connections every 30 minutes
    pool_size=10,            # base pool size
    max_overflow=20,         # allow temporary bursts
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    """Create all tables in the database"""
    from app.models.client import Client
    from app.models.client_user import ClientUser
    from app.models.lead import Lead
    from app.models.knowledge_base import ClientDeployment, KnowledgeDocument
    from app.models.analytics import ClientDailyStats
    from app.models.automation import Sequence, SequenceStep, LeadSequenceState
    from app.models.form_contact import FormContact
    
    # Drop all existing tables first (safely for MySQL by disabling FK checks)
    with engine.connect() as conn:
        try:
            # Disable foreign key checks for MySQL
            conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0;")
        except Exception:
            # Non-MySQL engines will error here; ignore
            pass

        # Perform drop with full metadata (all models imported above)
        Base.metadata.drop_all(bind=engine)

        try:
            # Re-enable foreign key checks for MySQL
            conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1;")
        except Exception:
            pass

    # Create all tables
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created successfully")

def ensure_tables():
    """Create any missing tables without dropping existing data (safe for startup)."""
    from app.models.client import Client
    from app.models.client_user import ClientUser
    from app.models.lead import Lead
    from app.models.knowledge_base import ClientDeployment, KnowledgeDocument
    from app.models.analytics import ClientDailyStats
    from app.models.form_contact import FormContact
    
    Base.metadata.create_all(bind=engine)
    print("✅ Ensured database tables exist")
