"""Add rate limiting to existing FastAPI main.py."""

with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\main.py', 'r') as f:
    content = f.read()

# Add rate limiting after the CORS middleware
old_section = """app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Camera router"""

new_section = """app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware - 100 requests per minute per IP
request_history = __import__("collections").defaultdict(list)

@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    client_ip = request.client.host
    current_time = __import__("time").time()
    request_history[client_ip] = [
        ts for ts in request_history[client_ip]
        if current_time - ts < 60
    ]
    if len(request_history[client_ip]) >= 100:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    request_history[client_ip].append(current_time)
    return await call_next(request)

# Camera router"""

if old_section in content:
    content = content.replace(old_section, new_section)
    print('Rate limiting middleware added to main.py')
else:
    print('Pattern not found - checking existing structure')

with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\main.py', 'w') as f:
    f.write(content)
print('Done')