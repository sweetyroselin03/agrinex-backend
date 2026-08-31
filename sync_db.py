import os
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

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

def sync_db(bind_engine=None):
    if bind_engine is None:
        from app.database import engine as default_engine
        bind_engine = default_engine

    print("Syncing Database Schema...")
    
    with bind_engine.connect() as conn:
        # Users table column sync
        add_column_if_missing(conn, "users", "phone", "VARCHAR")
        add_column_if_missing(conn, "users", "full_name", "VARCHAR")
        add_column_if_missing(conn, "users", "username", "VARCHAR")
        add_column_if_missing(conn, "users", "hashed_password", "VARCHAR")
        add_column_if_missing(conn, "users", "village", "VARCHAR")
        add_column_if_missing(conn, "users", "district", "VARCHAR")
        add_column_if_missing(conn, "users", "state", "VARCHAR")
        add_column_if_missing(conn, "users", "farm_size", "VARCHAR")
        add_column_if_missing(conn, "users", "experience", "VARCHAR")
        add_column_if_missing(conn, "users", "crop_specialization", "VARCHAR")
        add_column_if_missing(conn, "users", "crop_types", "VARCHAR")
        add_column_if_missing(conn, "users", "profile_picture", "VARCHAR")
        add_column_if_missing(conn, "users", "bio", "VARCHAR")
        add_column_if_missing(conn, "users", "website", "VARCHAR")
        add_column_if_missing(conn, "users", "is_verified", "BOOLEAN DEFAULT TRUE")
        add_column_if_missing(conn, "users", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        
        # Other tables column sync
        add_column_if_missing(conn, "chat_messages", "conversation_id", "VARCHAR")
        add_column_if_missing(conn, "posts", "images", "TEXT")
        add_column_if_missing(conn, "posts", "hashtags", "VARCHAR")
        add_column_if_missing(conn, "posts", "location", "VARCHAR")
        add_column_if_missing(conn, "posts", "crop_category", "VARCHAR")

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
    Base.metadata.create_all(bind=bind_engine)
    print("\nDatabase sync completed successfully!")

if __name__ == "__main__":
    sync_db()

