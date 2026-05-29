import os
from sqlalchemy import create_engine, MetaData, Table, select
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def check_otps():
    db = SessionLocal()
    try:
        # Reflect the table
        metadata = MetaData()
        otp_codes = Table('otp_codes', metadata, autoload_with=engine)
        
        # Query
        stmt = select(otp_codes).order_by(otp_codes.c.last_sent_at.desc()).limit(5)
        results = db.execute(stmt).fetchall()
        
        print(f"Found {len(results)} OTP entries:")
        for row in results:
            print(row)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    check_otps()
