from sqlalchemy import Column, String, Date, Integer, ForeignKey, UniqueConstraint, DateTime
from sqlalchemy.sql import func
from app.database import Base


class ClientDailyStats(Base):
    __tablename__ = "client_daily_stats"

    # Composite primary key via unique constraint and surrogate id for compatibility
    id = Column(String(36), primary_key=True)
    client_id = Column(String(36), ForeignKey("clients.client_id"), nullable=False)
    date = Column(Date, nullable=False)  # UTC date

    messages_user = Column(Integer, nullable=False, default=0)
    messages_bot = Column(Integer, nullable=False, default=0)
    sessions_started = Column(Integer, nullable=False, default=0)
    leads_created = Column(Integer, nullable=False, default=0)
    leads_qualified = Column(Integer, nullable=False, default=0)
    contacts_captured = Column(Integer, nullable=False, default=0)

    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('client_id', 'date', name='uq_client_daily_date'),
    )
