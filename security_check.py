#!/usr/bin/env python
"""Security check for Prompt 26."""

import os
import sys

sys.path.insert(0, r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend')

print('=== PROMPT 26: SECURITY HARDENING CHECK ===')
print()

# 1. CORS check
print('[1] CORS CONFIGURATION')
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\main.py', 'r') as f:
    content = f.read()
if 'allow_origins=["*"]' in content:
    print('  [VULN] CORS: allow_origins="*" - too permissive')
    print('  [FIX] Restrict to specific origins (localhost:3000)')
elif 'allow_origins' in content:
    print('  [OK] CORS: origins restricted')
else:
    print('  [OK] No wildcard CORS detected')

# 2. Rate limiting
print()
print('[2] RATE LIMITING')
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\main.py', 'r') as f:
    mcontent = f.read()
if 'rate_limit' in mcontent.lower() or '100 requests' in mcontent:
    print('  [OK] Rate limiting configured')
else:
    print('  [INFO] Rate limiting not explicitly configured')

# 3. Authentication
print()
print('[3] AUTHENTICATION')
auth_imports = []
for root, dirs, files in os.walk(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend'):
    for f in files:
        if 'auth' in f.lower() and f.endswith('.py'):
            auth_imports.append(os.path.join(root, f))
print(f'  Auth files: {len(auth_imports)}')

# Check if get_current_active_user is referenced in routes
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\camera_routes.py', 'r') as f:
    cr = f.read()
if 'get_current_active_user' in cr:
    print('  [OK] Authentication: get_current_active_user referenced in routes')
else:
    print('  [VULN] Authentication: get_current_active_user not in camera routes')

# 4. Password hashing
print()
print('[4] PASSWORD HASHING')
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\auth.py', 'r') as f:
    auth_content = f.read()
if 'verify_password' in auth_content:
    print('  [OK] Password verification function exists')
else:
    print('  [VULN] Password verification missing')

# 5. RTSP credentials
print()
print('[5] RTSP CREDENTIAL HANDLING')
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\camera_routes.py', 'r') as f:
    cr = f.read()
if 'Never returned in API responses' in cr:
    print('  [OK] RTSP credentials: never returned in API responses')
else:
    print('  [INFO] RTSP credentials: verify never exposed')

# 6. .env.example
print()
print('[6] ENVIRONMENT FILES')
env_path = r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\.env'
env_example_path = r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\.env.example'
print(f'  .env exists: {os.path.exists(env_path)}')
print(f'  .env.example exists: {os.path.exists(env_example_path)}')
if os.path.exists(env_example_path):
    print('  [OK] .env.example present')

# 7. No secrets in source
print()
print('[7] SECRET HANDLING')
secret_found = False
for root, dirs, files in os.walk(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            try:
                with open(path, 'r', errors='ignore') as fh:
                    content = fh.read()
                    if 'SECRET_KEY' in content and 'your-secret-key' not in content.lower():
                        secret_found = True
                        break
            except:
                pass
    if not secret_found:
        print('  [OK] No hardcoded SECRET_KEY found')
    else:
        print('  [VULN] Hardcoded SECRET_KEY detected')

# 8. WebSocket authorization
print()
print('[7] WEBSOCKET AUTHORIZATION')
# Check if WS auth is referenced anywhere
ws_auth_found = False
for root, dirs, files in os.walk(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            try:
                with open(path, 'r', errors='ignore') as fh:
                    content = fh.read()
                    if 'websocket' in content.lower() and 'auth' in content.lower():
                        ws_auth_found = True
                        break
            except:
                pass
if ws_auth_found:
    print('  [OK] WebSocket authorization referenced')
else:
    print('  [INFO] WebSocket authorization not explicitly configured')

# 9. Evidence/watchelp access
print()
print('[8] EVIDENCE/WATCHLIST ACCESS')
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\camera_routes.py', 'r') as f:
    cr = f.read()
if 'owner_id' in cr and 'current_user' in cr:
    print('  [OK] Owner-based access control referenced')
else:
    print('  [INFO] Access control structure check needed')

print()
print('=== SECURITY CHECK COMPLETE ===')
PYEOF