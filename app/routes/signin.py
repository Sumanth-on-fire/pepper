import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from app.services.appwrite_client import client_manager

try:
    from appwrite.services.users import Users
    from appwrite.services.account import Account
except ImportError:  # pragma: no cover - optional dependency handling
    Users = None
    Account = None

router = APIRouter()

logger = logging.getLogger('signin')


def _model_to_dict(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_map"):
        return value.to_map()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(getattr(value, "__dict__", {}))

@router.post("/", tags=['Authentication'])
async def signin(form_data: OAuth2PasswordRequestForm = Depends()):
    if Account is None or Users is None:
        raise HTTPException(status_code=500, detail="Appwrite SDK is not available in this environment.")

    identifier = form_data.username.strip()
    user_record = client_manager.find_user_by_email_or_username(identifier)
    if not user_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found. Please create an account first."
        )

    try:
        user_client = client_manager.get_user_client()
        account_service = Account(client=user_client)
        session = account_service.create_email_password_session(
            email=user_record.get("email") or identifier,
            password=form_data.password
        )
        session_payload = _model_to_dict(session)
        prefs = user_record.get("prefs") or {}
        user_id = session_payload.get("userId") or session_payload.get("user_id") or user_record.get("$id")
        bucket_id = client_manager.get_user_bucket_id(user_id, create_if_missing=True)

        return {
            "access_token": session_payload.get("secret") or getattr(session, "secret", None),
            "token_type": "bearer",
            "user_id": user_id,
            "bucket_id": bucket_id,
            "expires_at": session_payload.get("expire") or getattr(session, "expire", None),
            "email": user_record.get("email"),
            "display_name": user_record.get("name") or prefs.get("display_name") or prefs.get("username"),
            "username": prefs.get("username") or user_record.get("email"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signin Failure: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username and password combination is not present."
        )
        
