import os
from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from app.database import Base
from app import models

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

def sync_db():
    print("Syncing database schema...")
    metadata = MetaData()
    
    # Check if otp_codes exists and drop it
    try:
        otp_table = Table('otp_codes', metadata, autoload_with=engine)
        print("Dropping old otp_codes table...")
        otp_table.drop(engine)
    except Exception as e:
        print(f"Note: Could not drop otp_codes: {e}")

    # Recreate all tables based on models
    print("Creating tables from models...")
    models.Base.metadata.create_all(bind=engine)
    print("Sync complete!")

if __name__ == "__main__":
    sync_db()
