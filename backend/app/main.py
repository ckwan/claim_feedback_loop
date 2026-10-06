from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app.routers import claims_route, feedback_route, setup_route, suggestions_route

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Claims Feedback Loop — Practice API")

app.include_router(setup_route.router)
app.include_router(claims_route.router)
app.include_router(suggestions_route.router)
app.include_router(feedback_route.router)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For dev, later restrict to frontend domain
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/health")
def health():
    return {"status": "ok"}
