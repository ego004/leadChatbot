from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.routers import admin, client_config, knowledge_base, chat, client_dashboard, leads_dashboard, automation, auth, form
from app.routers.ingestion import router as ingestion_router
from app.database import engine, Base, ensure_tables
from app.services.db_migrations import run_lightweight_migrations
from app.models import analytics  # ensure ClientDailyStats is registered
from app.models import client_user  # ensure ClientUser is registered
from app.services.vector_store_service import preload_embeddings
from app.services.service_manager import service_manager
import logging

# Module logger
logger = logging.getLogger(__name__)
# Avoid destructive operations at import time; ensure tables will be created on startup

# Create FastAPI app
app = FastAPI(
    title="LeadGenius AI - Complete Platform",
    description="Complete lead generation chatbot platform with admin management, client dashboards, and email automation",
    version="3.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
# Routers that define non-"/api" prefixes need a global "/api" prefix (admin, auth)
app.include_router(admin.router, prefix="/api")
app.include_router(auth.router, prefix="/api")

# Routers that already include "/api" in their own prefixes should be included as-is
app.include_router(knowledge_base.router)
app.include_router(client_config.router)
app.include_router(chat.router)
app.include_router(client_dashboard.router)
app.include_router(leads_dashboard.router)
app.include_router(automation.router)
app.include_router(ingestion_router)
app.include_router(form.router)

# Mount minimal static admin UI
app.mount("/api/admin-ui", StaticFiles(directory="frontend", html=True), name="admin-ui")

@app.on_event("startup")
async def startup_event():
    """Start background services on app startup"""
    try:
        # Ensure DB tables exist (non-destructive)
        ensure_tables()
        try:
            # Run lightweight in-code migrations (add missing columns, etc.)
            run_lightweight_migrations(engine)
        except Exception as e:
            logger.warning(f"Lightweight migrations failed: {e}")
        # Warm embeddings model to avoid first-request latency
        preload_embeddings()
        logger.info("Embeddings preloaded")
        
        # Preload service manager singletons
        service_manager.preload_services()
        logger.info("Service singletons preloaded")
    except Exception as e:
        logger.warning(f"Failed to preload embeddings/services: {e}")

@app.get("/api/")
def read_root():
    return {"message": "LeadGenius AI Backend API", "version": "3.0.0"}

@app.get("/api/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
