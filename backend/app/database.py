import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./claims.db")

# SQLite needs this connect_arg; Postgres ignores it if present via the branch below.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


def session_is_postgres(db) -> bool:
    """Whether this session talks to Postgres. Checks the session, not the global engine."""
    return db.get_bind().dialect.name == "postgresql"


def create_dev_schema() -> None:
    """Create tables directly from the models. Used for SQLite (local, tests).

    On Postgres the schema belongs to Alembic (`alembic upgrade head`), because it
    needs things create_all cannot do well: the pgvector extension, an HNSW index,
    a generated tsvector column. The chunks table is Postgres only, so it is skipped
    here.
    """
    tables = [t for t in Base.metadata.sorted_tables if t.name != "claim_chunks"]
    Base.metadata.create_all(bind=engine, tables=tables)
