import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

# Import model and Base
from app.models.form_contact import FormContact


def main():
    # Get DB URL from CLI or env
    db_url = None
    if len(sys.argv) > 1:
        db_url = sys.argv[1]
    else:
        db_url = os.getenv("DATABASE_URL") or os.getenv("DB_URL")

    if not db_url:
        print("Usage: python scripts/create_form_contacts_table.py <SQLALCHEMY_DATABASE_URL>")
        print("Or set DATABASE_URL env var.")
        sys.exit(1)

    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        # Create only the formContacts table
        FormContact.__table__.create(bind=engine, checkfirst=True)
        print("✅ Created or verified table 'formContacts'.")
    except SQLAlchemyError as e:
        print(f"❌ Failed to create table: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
