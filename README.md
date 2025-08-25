# LeadGenius AI Backend

A fully managed AI chatbot service for automated lead capture and nurturing.

## Features

- **Intelligent AI Chatbot**: 24/7 website chatbot with RAG (Retrieval Augmented Generation)
- **Automated Lead Capture**: Smart lead detection using LLM function calling
- **Follow-up Automation**: Email and WhatsApp sequences with smart pause on replies
- **WhatsApp Live Chat**: Handoff to human agents with "TALK" command
- **Admin Panel API**: Complete client and lead management
- **Web Scraping**: Automated website content ingestion with crawl4ai

## Tech Stack

- **Backend**: FastAPI, PostgreSQL, Celery, Redis
- **AI/ML**: OpenAI GPT, ChromaDB, Sentence Transformers
- **Web Scraping**: crawl4ai with deep crawling support
- **Authentication**: JWT with role-based access (Admin/Client)

## Quick Start

### 1. Environment Setup

```bash
# Copy environment file
cp .env.example .env

# Edit .env with your configuration
# - Database URL (PostgreSQL)
# - OpenAI API Key
# - Redis URL
# - JWT Secret
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Database Setup

```bash
# Initialize Alembic
alembic init alembic

# Create initial migration
alembic revision --autogenerate -m "Initial migration"

# Run migrations
alembic upgrade head
```

### 4. Start Services

```bash
# Start Redis (required for Celery)
redis-server

# Start Celery Worker (in separate terminal)
celery -A app.tasks.celery_app worker --loglevel=info

# Start Celery Beat for scheduled tasks (in separate terminal)
celery -A app.tasks.celery_app beat --loglevel=info

# Start FastAPI server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API Endpoints

### Admin Endpoints (JWT Required)

- `POST /clients` - Create new client
- `GET /clients` - List all clients
- `GET /clients/{id}` - Get client details
- `PUT /clients/{id}` - Update client
- `POST /clients/{id}/ingest` - Trigger website crawling

### Client Dashboard Endpoints (JWT Required)

- `GET /leads` - List leads for authenticated client
- `GET /leads/{id}` - Get lead details with chat history
- `PUT /leads/{id}` - Update lead status

### Public Endpoints

- `POST /chat` - Main chat endpoint for widget
- `POST /webhooks/reply` - Webhook for email/WhatsApp replies

## Usage Flow

### 1. Client Onboarding (Admin)

```bash
# Create client
curl -X POST "http://localhost:8000/clients" \
  -H "Authorization: Bearer YOUR_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "website_url": "https://acme.com"}'

# Trigger website ingestion
curl -X POST "http://localhost:8000/clients/{client_id}/ingest" \
  -H "Authorization: Bearer YOUR_ADMIN_JWT"
```

### 2. Chat Widget Integration

```javascript
// Example chat widget usage
const response = await fetch('/chat', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    client_id: 'client-uuid',
    session_id: sessionId, // null for new session
    query: 'What are your pricing plans?'
  })
});

const data = await response.json();
// Handle response_type: "text" or "lead_captured"
```

### 3. WhatsApp Live Chat

Users can type "TALK", "human", or "live chat" to request human handoff.

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Chat Widget   │────│   FastAPI API    │────│   PostgreSQL    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                       ┌────────┴────────┐
                       │                 │
                ┌──────▼──────┐   ┌─────▼─────┐
                │   ChromaDB  │   │   Redis   │
                │ (Vector DB) │   │ (Celery)  │
                └─────────────┘   └───────────┘
```

## Key Components

- **Client Management**: CRUD operations for clients and configurations
- **Ingestion Pipeline**: crawl4ai → cleaning → chunking → vector embeddings
- **Chat Engine**: RAG + LLM function calling for lead capture
- **Automation Engine**: Email/WhatsApp sequences with smart pausing
- **Webhook Handler**: Secure HMAC-verified webhook for reply handling

## Development

### Running Tests

```bash
pytest
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Production Deployment

1. Set up PostgreSQL and Redis instances
2. Configure environment variables
3. Run database migrations
4. Deploy with proper WSGI server (gunicorn)
5. Set up Celery workers and beat scheduler
6. Configure reverse proxy (nginx)

## Security Notes

- All admin endpoints require JWT authentication
- Webhook endpoints use HMAC signature verification
- CORS is configured for production domains
- Sensitive data stored in environment variables
