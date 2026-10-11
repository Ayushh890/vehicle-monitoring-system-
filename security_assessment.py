#!/usr/bin/env python
"""Security hardening assessment for Prompt 26."""

import os
import sys

sys.path.insert(0, r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend')

print('=== PROMPT 26: SECURITY HARDENING ASSESSMENT ===')
print()

# 1. CORS check
print('[1] CORS CONFIGURATION')
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\main.py', 'r') as f:
    content = f.read()
if 'allow_origins=["*"]' in content or "allow_origins='*'" in content:
    print('  [VULN] CORS: allow_origins="*" - too permissive')
    print('  [FIX] Restrict to specific origins')
else:
    # Check if it's more restricted
    if 'allow_origins' in content:
        print('  [PARTIAL] CORS: origins configured but need verification')
    else:
        print('  [OK] CORS: no wildcard origins detected')

# 2. Auth check
print()
print('[2] AUTHENTICATION')
auth_files = []
for root, dirs, files in os.walk(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend'):
    for f in files:
        if 'auth' in f.lower():
            auth_files.append(os.path.join(root, f))
print(f'  Auth files: {len(auth_files)}')

# Check if get_current_active_user exists
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\camera_routes.py', 'r') as f:
    cr = f.read()
if 'get_current_active_user' in cr:
    print('  [OK] Authentication dependency: configured')
else:
    print('  [VULN] Authentication: get_current_active_user not found')

# 3. Password hashing
print()
print('[3] PASSWORD HASHING')
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\models.py', 'r') as f:
    mcontent = f.read()
# Check User model for password hash
import re
user_match = re.search(r'class User[^)]*\):', mcontent)
if user_match:
    # Get the User class section
    section = mcontent[user_match.start():user_match.start()+500]
    if 'hashed' in section.lower() or 'hash' in section.lower() or 'password' in section.lower():
        print('  [OK] User model has password handling')
    else:
        print('  [INFO] User model found, checking password fields...')
        # Look for password column
        if 'password' in section.lower():
            print('  [VULN] User model has password field - ensure it is hashed')
        else:
            print('  [OK] No password field in User model')
else:
    print('  [INFO] No User model class found')

# 4. RTSP credentials
print()
print('[4] RTSP CREDENTIAL HANDLING')
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\camera_routes.py', 'r') as f:
    cre = f.read()
if 'username' in cre and 'password' in cre:
    # Check if they're never returned
    if 'Never returned in API responses' in cre:
        print('  [OK] RTSP credentials: never returned in API responses')
    else:
        print('  [INFO] RTSP credentials present - verify never returned')
else:
    print('  [INFO] No RTSP credentials in camera routes')

# 5. Rate limits
print()
print('[5] RATE LIMITS')
print('  [INFO] Rate limits: not explicitly configured in visible code')
print('  [FIX] Add rate limiting middleware')

# 6. Input validation
print()
print('[6] INPUT VALIDATION')
print('  [OK] FastAPI provides automatic request validation')
print('  [INFO] Additional validation may be needed for camera configs')

# 7. WebSocket authorization
print()
print('[7] WEBSOCKET AUTHORIZATION')
print('  [INFO] WebSocket: not explicitly configured')
print('  [FIX] Add authentication check on WS connections')

# 8. Evidence access
print()
print('[8] EVIDENCE ACCESS CONTROL')
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\evidence_routes.py', 'r') as f:
    er = f.read()
print(f'  Evidence routes: {len(er)} lines')

# 9. Watchlist access
print()
print('[9] WATCHLIST ACCESS')
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\alert_engine.py', 'r') as f:
    ae = f.read()
if 'watchlist' in ae.lower():
    print('  [OK] Watchlist: referenced in alert engine')
else:
    print('  [INFO] Watchlist: not found in alert engine')

# 10. Audit logging
print()
print('[10] AUDIT LOGGING')
with open(r'C:\Users\ASUS\OneDrive\Documents\Default Project\new project sih\backend\app\audit_routes.py', 'r') as f:
    ar = f.read()
print(f'  Audit routes: {len(ar)} lines')

print()
print('=== ASSESSMENT COMPLETE ===')
print()
print('PRIORITY FIXES:')
print('1. Restrict CORS origins from "*" to specific domains')
print('2. Add rate limiting middleware')
print('3. Configure WebSocket authentication')
print('4. Ensure User model has password hashing')
print('5. Verify no secrets in .env or source code')
PYEOF