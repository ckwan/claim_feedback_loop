from fastapi import FastAPI

from app.database import Base, engine
from app.routers import claims_route, feedback_route, setup_route, suggestions

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Claims Feedback Loop — Practice API")

app.include_router(setup_route.router)
app.include_router(claims_route.router)
app.include_router(suggestions.router)
app.include_router(feedback_route.router)


@app.get("/health")
def health():
    return {"status": "ok"}
