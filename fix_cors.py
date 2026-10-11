"""Fix CORS configuration to restrict origins."""

with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\main.py', 'r') as f:
    content = f.read()

old_cors = """app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)"""

new_cors = """app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)"""

if old_cors in content:
    content = content.replace(old_cors, new_cors)
    print('CORS configuration restricted')
else:
    print('CORS pattern not found')

with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\main.py', 'w') as f:
    f.write(content)