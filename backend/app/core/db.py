from sqlmodel import create_engine

from app.core.config import settings

# Tables are created and changed with Alembic migrations (scripts/prestart.sh).
engine = create_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
