"""AI Ops Copilot FastAPI application."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import routers
from app.routes.health import router as health_router
from app.routes.logs import router as logs_router
from app.routes.projects import router as projects_router
from app.routes.incidents import router as incidents_router
from app.routes.agents import router as agents_router

# Create app
app = FastAPI(
    title="AI Ops Copilot",
    description="Production-grade AIOps backend",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(logs_router)
app.include_router(projects_router)
app.include_router(incidents_router)
app.include_router(agents_router)

@app.get("/")
def root():
    """API root."""
    return {
        "service": "AI Ops Copilot",
        "version": "1.0.0",
        "docs": "/docs"
    }

