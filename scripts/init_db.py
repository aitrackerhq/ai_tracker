"""Create SQLite tables. Idempotent."""
from backend.database.session import engine
from backend.models import Base

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("OK: tables created.")
