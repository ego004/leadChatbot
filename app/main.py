from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.routers import admin, client_config, knowledge_base, chat, client_dashboard, leads_dashboard, email_chat, automation, auth
from app.database import engine, Base
from app.services.db_migrations import run_lightweight_migrations
from app.services.email_monitor import start_email_monitoring
import asyncio
from app.models import analytics  # ensure ClientDailyStats is registered

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

# Serve static frontend (development convenience)
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

@app.on_event("startup")
async def startup_event():
    """Start background services on app startup"""
    try:
        await start_email_monitoring()
        print("✅ Email monitoring service started")
    except Exception as e:
        print(f"⚠️ Failed to start email monitoring: {e}")

@app.get("/")
def read_root():
    return {"message": "LeadGenius AI Backend API", "version": "3.0.0"}

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard():
    try:
        with open("frontend/admin.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "<h1>Admin Dashboard</h1><p>frontend/admin.html not found.</p>"

@app.get("/client", response_class=HTMLResponse)
def client_dashboard_page():
    try:
        with open("frontend/client.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "<h1>Client Dashboard</h1><p>frontend/client.html not found.</p>"

@app.get("/chat", response_class=HTMLResponse)
def public_chat_page():
    try:
        with open("frontend/client-chat.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "<h1>Chat</h1><p>frontend/client-chat.html not found.</p>"

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
