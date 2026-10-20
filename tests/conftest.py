"""Shared test setup.

Two kinds of tests:

  * SQLite, in memory. Fast. Covers the API, tenant isolation and the state machine.
  * Postgres with pgvector. Covers migrations, search and the agent's search tool.
    These need a Postgres server whose user can CREATE EXTENSION (a superuser, as in
    the docker-compose image). Set TEST_DATABASE_URL, or the default
    postgresql://claims:claims@localhost:5432/claims_test is used. When no server is
    reachable they are skipped, not failed.
"""
import os

# Set before anything imports `app`, so the module level engine is SQLite. Tests must
# never touch a developer's real database.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["LLM_PROVIDER"] = "stub"
for key in ("EMBEDDING_PROVIDER", "ANTHROPIC_API_KEY", "OLLAMA_MODEL"):
    os.environ.pop(key, None)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

TEST_PG_URL = os.getenv("TEST_DATABASE_URL", "postgresql://claims:claims@localhost:5432/claims_test")


def _create_sqlite_tables(engine):
    tables = [t for t in Base.metadata.sorted_tables if t.name != "claim_chunks"]
    Base.metadata.create_all(engine, tables=tables)


@pytest.fixture()
def sqlite_engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    _create_sqlite_tables(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(sqlite_engine):
    with sessionmaker(bind=sqlite_engine)() as session:
        yield session


def _client_for(engine):
    factory = sessionmaker(bind=engine, autoflush=False)

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    return TestClient(app)


@pytest.fixture()
def client(sqlite_engine):
    yield _client_for(sqlite_engine)
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def pg_engine():
    url = make_url(TEST_PG_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    except OperationalError:
        pytest.skip("No Postgres server reachable for the pgvector tests")
    finally:
        admin.dispose()

    # Build the schema with the real migrations, so they are tested on every run.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_PG_URL
    try:
        cfg = Config(os.path.join(os.path.dirname(__file__), "..", "backend", "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "backend", "migrations"))
        command.upgrade(cfg, "head")
    finally:
        os.environ["DATABASE_URL"] = previous or "sqlite://"
    engine = create_engine(TEST_PG_URL)
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_db(pg_engine):
    """A Postgres session on an empty database."""
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with pg_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    with sessionmaker(bind=pg_engine, autoflush=False)() as session:
        yield session


@pytest.fixture()
def pg_client(pg_engine, pg_db):
    yield _client_for(pg_engine)
    app.dependency_overrides.clear()


# --- helpers ---------------------------------------------------------------------------


def make_org(client, name="Org"):
    org_id = client.post("/organizations", json={"name": name}).json()["id"]
    return org_id, {"X-Org-Id": org_id}


def make_claim(client, org_id, headers, notes="Water damage in the kitchen.", amount=500.0, name="Claimant"):
    res = client.post(
        "/claims", headers=headers,
        json={"org_id": org_id, "claimant_name": name, "amount": amount, "history_notes": notes},
    )
    assert res.status_code == 200, res.text
    return res.json()


def make_adjuster(client, org_id, email="adj@example.com"):
    return client.post(
        "/adjusters", json={"org_id": org_id, "name": "Adj", "email": email}
    ).json()["id"]
