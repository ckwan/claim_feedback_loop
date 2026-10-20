from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import create_dev_schema, is_postgres
from app.routers import claims, feedback, investigate, search, setup, suggestions

# On Postgres the schema comes from `alembic upgrade head` (see migrations/).
# SQLite is for quick local runs and tests, so it is created directly.
if not is_postgres():
    create_dev_schema()

app = FastAPI(title="Claims Feedback Loop — Practice API")

# Local dev only: the Vite frontend runs on a different origin/port. A real
# deployment would scope this to the actual frontend's origin, not "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(setup.router)
app.include_router(search.router)  # before claims: /claims/search must not match /claims/{id}
app.include_router(claims.router)
app.include_router(suggestions.router)
app.include_router(feedback.router)
app.include_router(investigate.router)


@app.get("/health")
def health():
    return {"status": "ok"}
