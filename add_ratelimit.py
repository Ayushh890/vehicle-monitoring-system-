"""Add rate limiting middleware to FastAPI app."""

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from collections import defaultdict
import time

app = FastAPI(
    title="SIH26127 Backend",
    description="Backend for SIH26127 project - AI event pipeline",
    version="0.1.0",
)

# CORS - restricted origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware
request_history = defaultdict(list)  # client_ip -> list of timestamps

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Simple rate limiter - 100 requests per minute per IP."""
    client_ip = request.client.host
    current_time = time.time()
    
    # Remove timestamps older than 60 seconds
    request_history[client_ip] = [
        ts for ts in request_history[client_ip]
        if current_time - ts < 60
    ]
    
    # Check if under limit (100 requests per minute)
    if len(request_history[client_ip]) >= 100:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    # Add current request timestamp
    request_history[client_ip].append(current_time)
    
    response = await call_next(request)
    return response

# Health endpoints
@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": "backend"}


@app.get("/ready", tags=["health"])
async def ready() -> dict:
    return {"status": "ready", "service": "backend"}