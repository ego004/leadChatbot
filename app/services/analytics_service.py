from datetime import datetime, timezone, date
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.analytics import ClientDailyStats
import uuid


def utc_today_date() -> date:
    return datetime.now(timezone.utc).date()


def increment_stats(
    db: Session,
    client_id: str,
    date_value: date | None = None,
    **increments: int,
) -> None:
    """Increment daily counters for a client. Creates the row if missing.
    Example: increment_stats(db, client_id, messages_user=1)
    """
    d = date_value or utc_today_date()

    row = db.query(ClientDailyStats).filter(
        and_(ClientDailyStats.client_id == client_id, ClientDailyStats.date == d)
    ).first()

    if not row:
        row = ClientDailyStats(
            id=str(uuid.uuid4()),
            client_id=client_id,
            date=d,
        )
        db.add(row)
        # set provided counters
        for k, v in increments.items():
            if hasattr(row, k) and isinstance(v, int):
                setattr(row, k, v)
        db.commit()
        return

    # increment existing counters
    changed = False
    for k, v in increments.items():
        if hasattr(row, k) and isinstance(v, int) and v:
            current = getattr(row, k) or 0
            setattr(row, k, current + v)
            changed = True
    if changed:
        db.commit()
