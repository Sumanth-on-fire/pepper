import logging

from fastapi import APIRouter, HTTPException, Query, status

from app.models.signup import UserSignupModel
from app.services.appwrite_client import client_manager

try:
    from appwrite.services.users import Users
    from appwrite.id import ID
except ImportError:  # pragma: no cover - optional dependency handling
    Users = None
    ID = None

router = APIRouter()

logger = logging.getLogger("appwrite_client")

@router.post('/', status_code=status.HTTP_201_CREATED, tags=['Authentication'])
async def signup(user_data: UserSignupModel):
    if Users is None or ID is None:
        raise HTTPException(status_code=500, detail="Appwrite SDK is not available in this environment.")

    try:
        admin_client = client_manager.get_admin_client()
        users_service = Users(admin_client)
        
        new_user = users_service.create(
            user_id=ID.unique(),
            email=user_data.email,
            password=user_data.password,
            name=f"{user_data.display_name or user_data.username or ''} {user_data.username or ''}".strip()
        )
        users_service.update_prefs(
            user_id=new_user.id,
            prefs={
                "username": user_data.username or "",
                "display_name": user_data.display_name or "",
            },
        )
        profile_saved = True
        try:
            client_manager.upsert_user_profile(
                user_id=new_user.id,
                email=user_data.email,
                username=user_data.username,
                display_name=user_data.display_name,
            )
            bucket_id = client_manager.ensure_user_bucket(new_user.id)
        except Exception as profile_exc:
            profile_saved = False
            bucket_id = None
            logger.warning("Profile save skipped after auth signup: %s", profile_exc)
        
        return {
            "status": "success",
            "user_id": new_user.id,
            "email": user_data.email,
            "username": user_data.username,
            "display_name": user_data.display_name,
            "profile_saved": profile_saved,
            "bucket_id": bucket_id,
            "message": "User registered successfully. You can sign in now."
        }
        
    except Exception as e:
        logger.error(f"Signup Failure: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Registration failed: {str(e)}"
        )


# --- NEWLY ADDED CONFIRM ROUTE ---
@router.get('/confirm', tags=['Authentication'])
async def confirm_email(
    userId: str = Query(..., description="Appwrite verification user ID"),
    secret: str = Query(..., description="Appwrite verification token")
):
    try:
        from appwrite.services.account import Account
    except ImportError:  # pragma: no cover
        Account = None

    if Account is None or Users is None:
        raise HTTPException(status_code=500, detail="Appwrite SDK is not available in this environment.")
    """
    Landing endpoint processing the email confirmation token.
    Updates verification status on Appwrite and automatically returns a logged-in user session.
    """
    try:
        # Step 1: Use an unauthenticated baseline client to submit the secret email verification
        base_client = client_manager.get_admin_client()
        account_service = Account(base_client)
        
        # This completes the verification workflow on Appwrite, flipping 'emailVerification' to true
        account_service.update_verification(user_id=userId, secret=secret)
        
        # Step 2: Auto-login sequence via Admin client privilege
        # We target the administrative Users service to establish a new token session without forcing a password re-entry
        users_service = Users(base_client)
        session = users_service.create_token(user_id=userId)
        
        # Return the newly active token and account payload back to the client application
        return {
            "status": "success",
            "message": "Your email has been verified! Auto-login complete.",
            "access_token": session.secret,
            "token_type": "bearer",
            "user_id": userId,
            "expires_at": session.expire
        }
        
    except Exception as e:
        logger.error(f"Confirmation/Auto-Login Failure: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Email verification or automatic login failed: {str(e)}"
        )
