# Performance Test Instructions

## Quick Start

1. **Start the server** (with our optimizations):
   ```bash
   cd c:\Users\ego\projects\leadChatbot
   .\.venv\Scripts\Activate.ps1
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Watch startup logs** for our optimization confirmations:
   ```
   ✅ Embeddings preloaded
   ✅ GeminiService singleton initialized  
   ✅ Service singletons preloaded
   ```

3. **Run the performance test**:
   ```bash
   # In a new terminal
   .\.venv\Scripts\Activate.ps1
   python scripts\e2e_full_flow.py --admin-email admin@example.com --admin-password ChangeMe123!
   ```

## What the Test Does

1. **Creates a new client** via admin API
2. **Configures deployment** (custom_client_id + token)
3. **Adds knowledge base content** 
4. **Triggers ingestion** (if available)
5. **Sends multiple chat messages** with response time measurements
6. **Provides performance summary**

## Expected Results

**Before optimization**: 4-6 seconds per chat
**After optimization**: 1-2 seconds per chat

### Performance Benchmarks:
- ✅ **Excellent**: < 2.5s average
- ⚡ **Good**: < 4.0s average (improved)  
- ⚠️ **Needs work**: > 4.0s average

## Server Logs to Monitor

Watch for these patterns in server logs:

### Startup (Good):
```
✅ Embeddings preloaded
✅ GeminiService singleton initialized
✅ Service singletons preloaded
```

### First Request (Should NOT see):
```
❌ BAD: "Initialized SentenceTransformerEmbeddings singleton"
❌ BAD: "GeminiService singleton initialized" (after startup)
```

### Subsequent Requests (Good):
```
✅ No service initialization logs
✅ Fast response times
```

## Troubleshooting

If response times are still slow:

1. **Check singleton loading**:
   - Restart server, watch startup logs
   - Ensure no service initialization during requests

2. **Check database connection**:
   - Verify Supabase configuration
   - Check network latency to Supabase

3. **Check model loading**:
   - Ensure sentence transformers model loads once at startup
   - Verify `all-MiniLM-L6-v2-binonly/` directory exists

## Manual Testing

You can also test individual endpoints:

```bash
# Health check
curl http://localhost:8000/api/health

# Chat (replace tokens)
curl -X POST "http://localhost:8000/api/chat/{custom_client_id}/message" \
  -H "x-deployment-token: your-token" \
  -d "message=Hello&return_sources=true"
```
