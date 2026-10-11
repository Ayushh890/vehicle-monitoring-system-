from contextlib import contextmanager

@contextmanager
def get_db():
    """Dependency injection for database sessions."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    database_url = os.environ.get("DATABASE_URL", "sqlite:///./test.db")
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()