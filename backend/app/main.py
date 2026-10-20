from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import claims, feedback, setup, suggestions

Base.metadata.create_all(bind=engine)

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
app.include_router(claims.router)
app.include_router(suggestions.router)
app.include_router(feedback.router)


@app.get("/health")
def health():
    return {"status": "ok"}
