import logging

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import Settings
from app.models.signup import UserSignupModel
from app.services.supabase_client import get_supabase_client
from app.services.appwrite_client import client_manager
from appwrite.services.users import Users
from appwrite.services.account import Account
from appwrite.id import ID

router = APIRouter()

logger = logging.getLogger("appwrite_client")

@router.post('/', status_code=status.HTTP_201_CREATED, tags=['Authentication'])
async def signup(user_data: UserSignupModel):
    try:
        # Step A: Initialize the administrative manager to register the user entry
        settings = Settings()
        admin_client = client_manager.get_admin_client()
        users_service = Users(admin_client)
        
        new_user = users_service.create(
            user_id=ID.unique(),
            email=user_data.email,
            password=user_data.password,
            name=user_data.display_name or ""
        )
        
        # Step B: Appwrite requires an active user context to issue verification links.
        # Create a temporary backend session for the newly registered user.
        account_service = Account(admin_client)
        temp_session = account_service.create_email_password_session(
            email=user_data.email,
            password=user_data.password
        )
        temp_token = temp_session.secret
        
        # Step C: Instantiate a client scoped to the new user to fire the verification email
        user_client = client_manager.get_user_client(session_token=temp_token)
        user_account = Account(user_client)
        
        # Define where the user clicks the link in their mailbox. 
        # Appwrite appends ?userId=...&secret=... parameters to this URL.
        confirmation_url = f"{settings.APPWRITE_URL.rstrip('/')}/confirm" 
        user_account.create_verification(url=confirmation_url)
        
        # Step D: Immediately terminate the temporary session. 
        # The user remains locked out until they confirm via the emailed link.
        user_account.delete_session(session_id='current')
        
        return {
            "status": "success",
            "user_id": new_user.id,
            "message": "User registered successfully. Verification email sent to inbox."
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