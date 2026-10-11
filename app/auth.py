"""Authentication and authorization for SIH26127 backend."""

from fastapi import HTTPException, status
from fastapi.security import OAuth2PasswordBearer

# OAuth2 password bearer token flow
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Settings - in production, these should come from environment variables
SECRET_KEY = "your-secret-key-change-in-production"  # noqa: S105
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


# --- Simple Password Verification ---

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash.
    
    In production, use a proper password hashing library like bcrypt.
    This is a placeholder implementation for demonstration.
    """
    # Simple placeholder verification - in production use bcrypt/argon2
    return plain_password == hashed_password


def get_password_hash(password: str) -> str:
    """Create a password hash.
    
    In production, use bcrypt or argon2.
    This is a placeholder implementation for demonstration.
    """
    # Placeholder - hash the password simply for demonstration
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()


# --- Token Creation ---

def create_access_token(data: dict, expires_delta: int = None) -> str:
    """Create a JWT access token."""
    import time
    to_encode = data.copy()
    if expires_delta:
        expire = time.time() + expires_delta
    else:
        expire = time.time() + 60 * 15  # 15 minutes
    to_encode.update({"exp": expire})
    # Use jose to encode
    try:
        from jose import jwt as jose_jwt
        encoded_jwt = jose_jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    except ImportError:
        # Fallback: simple token
        import secrets
        return secrets.token_urlsafe(32)


# --- Authentication Helpers ---

def get_token_header(authorization: str = None) -> str:
    """Extract JWT token from Authorization header."""
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ")[1]
    return None


def get_current_user_payload(token: str) -> dict:
    """Get the current authenticated user payload from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        from jose import jwt as jose_jwt
        payload = jose_jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise Exception
    except Exception:
        raise credentials_exception
    
    # Placeholder - in production, fetch from DB
    return {"username": username, "is_active": True, "is_superuser": False}


def is_authenticated(token: str) -> bool:
    """Check if a JWT token is valid."""
    try:
        from jose import jwt as jose_jwt
        payload = jose_jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload is not None and "sub" in payload
    except Exception:
        return False


def check_admin_role(user_payload: dict) -> bool:
    """Check if the user has admin role."""
    return user_payload.get("is_superuser", False)


# --- Token Endpoint ---

def login_for_access_token(username: str, password: str) -> dict:
    """Login endpoint that returns JWT access token."""
    # Placeholder - in production, verify against DB
    # Verify password using the verify_password function
    if not verify_password(password, "$2b$12$placeholder_hash"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    access_token = create_access_token(
        data={"sub": username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}