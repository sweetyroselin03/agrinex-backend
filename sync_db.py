import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agrinex.db")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

def sync_db():
    print("Syncing Database Schema...")
    
    with engine.connect() as conn:
        # Add missing columns to users table
        try:
            print("Checking 'username' column...")
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR;"))
            conn.commit()
            print("DONE: 'username' column synced.")
        except Exception as e:
            print(f"ERROR: Could not add 'username': {e}")

        try:
            print("Checking 'experience' column...")
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS experience VARCHAR;"))
            conn.commit()
            print("DONE: 'experience' column synced.")
        except Exception as e:
            print(f"ERROR: Could not add 'experience': {e}")

        try:
            print("Checking 'crop_specialization' column...")
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS crop_specialization VARCHAR;"))
            conn.commit()
            print("DONE: 'crop_specialization' column synced.")
        except Exception as e:
            print(f"ERROR: Could not add 'crop_specialization': {e}")

        try:
            print("Updating 'farm_size' column type...")
            # We use USING to cast float to varchar
            conn.execute(text("ALTER TABLE users ALTER COLUMN farm_size TYPE VARCHAR USING farm_size::text;"))
            conn.commit()
            print("DONE: 'farm_size' type updated to VARCHAR.")
        except Exception as e:
            print(f"ERROR: Could not update 'farm_size' type: {e}")

        try:
            print("Checking 'conversation_id' column in 'chat_messages'...")
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS conversation_id VARCHAR;"))
            conn.commit()
            print("DONE: 'conversation_id' column synced.")
        except Exception as e:
            print(f"ERROR: Could not add 'conversation_id': {e}")

        try:
            print("Checking 'images' column in 'posts'...")
            try:
                conn.execute(text("SELECT images FROM posts LIMIT 1;"))
                print("DONE: 'images' column already exists in 'posts' table.")
            except Exception:
                conn.rollback()
                conn.execute(text("ALTER TABLE posts ADD COLUMN images TEXT;"))
                conn.commit()
                print("DONE: Added 'images' column to 'posts' table.")
        except Exception as e:
            print(f"ERROR: Could not add 'images' column to 'posts' table: {e}")

    print("\nDatabase sync completed successfully!")

if __name__ == "__main__":
    sync_db()
