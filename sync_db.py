import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agrinex.db")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

def add_column_if_missing(conn, table: str, column: str, col_type: str):
    try:
        conn.execute(text(f"SELECT {column} FROM {table} LIMIT 1;"))
        print(f"DONE: '{column}' column already exists in '{table}' table.")
    except Exception:
        conn.rollback()
        try:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type};"))
            conn.commit()
            print(f"DONE: Added '{column}' column to '{table}' table.")
        except Exception as e:
            conn.rollback()
            print(f"INFO: Could not add column '{column}' to '{table}': {e}")

def sync_db():
    print("Syncing Database Schema...")
    
    with engine.connect() as conn:
        add_column_if_missing(conn, "users", "username", "VARCHAR")
        add_column_if_missing(conn, "users", "experience", "VARCHAR")
        add_column_if_missing(conn, "users", "crop_specialization", "VARCHAR")
        add_column_if_missing(conn, "users", "website", "VARCHAR")
        add_column_if_missing(conn, "chat_messages", "conversation_id", "VARCHAR")
        add_column_if_missing(conn, "posts", "images", "TEXT")

        try:
            print("Cleaning duplicate follows before enforcing unique constraint...")
            conn.execute(text("""
                DELETE FROM follows
                WHERE id NOT IN (
                    SELECT MIN(id)
                    FROM follows
                    GROUP BY follower_id, following_id
                );
            """))
            conn.commit()
            print("DONE: Duplicate follows cleaned.")
        except Exception as e:
            conn.rollback()
            print(f"INFO: Skip duplicate follow cleanup: {e}")

        try:
            print("Creating unique index on follows (follower_id, following_id)...")
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS unique_follower_following ON follows (follower_id, following_id);"))
            conn.commit()
            print("DONE: Unique index on follows created.")
        except Exception as e:
            conn.rollback()
            print(f"INFO: Unique index creation: {e}")

    # Ensure all tables created via metadata
    from app.models import Base
    Base.metadata.create_all(bind=engine)
    print("\nDatabase sync completed successfully!")

if __name__ == "__main__":
    sync_db()
