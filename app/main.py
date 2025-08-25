from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.routers import admin, client_config, knowledge_base, chat, client_dashboard, leads_dashboard, email_chat, automation, auth
from app.routers.ingestion import router as ingestion_router
from app.database import engine, Base
from app.services.db_migrations import run_lightweight_migrations
from app.services.email_monitor import start_email_monitoring
import asyncio
from app.models import analytics  # ensure ClientDailyStats is registered
from app.models import client_user  # ensure ClientUser is registered
from app.services.vector_store_service import preload_embeddings

# Create database tables
Base.metadata.create_all(bind=engine)
# Run lightweight migrations to ensure new columns exist
try:
    run_lightweight_migrations(engine)
except Exception as e:
    print(f"⚠️ Lightweight migrations failed: {e}")

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
app.include_router(admin.router)
app.include_router(knowledge_base.router)
app.include_router(client_config.router)
app.include_router(chat.router)
app.include_router(client_dashboard.router)
app.include_router(automation.router)
app.include_router(email_chat.router)
app.include_router(auth.router)
app.include_router(ingestion_router)

# Mount minimal static admin UI
app.mount("/admin-ui", StaticFiles(directory="frontend", html=True), name="admin-ui")

@app.on_event("startup")
async def startup_event():
    """Start background services on app startup"""
    try:
        # Warm embeddings model to avoid first-request latency
        preload_embeddings()
        print("✅ Embeddings preloaded")
        await start_email_monitoring()
        print("✅ Email monitoring service started")
    except Exception as e:
        print(f"⚠️ Failed to start email monitoring: {e}")

@app.get("/")
def read_root():
    return {"message": "LeadGenius AI Backend API", "version": "3.0.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
