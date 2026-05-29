import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agrinex.db")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

print(f"Connecting to database: {DATABASE_URL}")
engine = create_engine(DATABASE_URL)

def clear_tables():
    # Ordered dependencies first to avoid constraint issues during standard deletes
    tables = [
        "chat_messages",
        "crop_scans",
        "notifications",
        "saved_posts",
        "likes",
        "comments",
        "follows",
        "posts",
        "users",
        "otp_codes"
    ]
    with engine.connect() as conn:
        for table in tables:
            try:
                print(f"Clearing table: {table}")
                # Try TRUNCATE with CASCADE for PostgreSQL
                conn.execute(text(f"TRUNCATE TABLE {table} CASCADE;"))
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                    conn.execute(text(f"DELETE FROM {table};"))
                    conn.commit()
                except Exception as ex:
                    print(f"Could not clear table {table}: {ex}")
        
        # Attempt to reset primary key sequence for users
        try:
            conn.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), 1, false);"))
            conn.commit()
            print("Reset 'users' table sequence.")
        except Exception:
            pass

    print("All tables cleared successfully!")

if __name__ == "__main__":
    clear_tables()
