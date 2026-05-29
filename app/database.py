from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agrinex.db")

# Fixing the URL for SQLAlchemy if it's using the 'postgres://' prefix (Heroku/older style)
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

if "sqlite" in SQLALCHEMY_DATABASE_URL:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
    # Production-optimized connection settings for Neon PostgreSQL
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,       # Verifies connection health before using it
        pool_recycle=300,         # Recycles connections every 5 min to prevent serverless database disconnects
        pool_size=10,             # Maintains a pool of active connections
        max_overflow=20           # Allows temporary overflow under peak loads
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
