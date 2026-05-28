import logging

from fastapi import APIRouter, Depends, HTTPException,status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from app.services.supabase_client import get_supabase_client
from app.services.appwrite_client import client_manager
from appwrite.services.users import Users
from appwrite.id import ID
from appwrite.services.account import Account
from appwrite.client import Client

router = APIRouter()

logger = logging.getLogger('signin')

@router.post("/", tags=['Authentication'])
async def signin(form_data: OAuth2PasswordRequestForm = Depends()):
    try:
        # 1. Create a CLEAN User/Guest client (STRICTLY NO API KEY)
        user_client = client_manager.get_user_client()
        # Request the user session from a clean context to satisfy regional routing rules
        account_service = Account(client=user_client)
        session = account_service.create_email_password_session(
            email=form_data.username,
            password=form_data.password
        )

        # 2. Grab your standard authorized admin client for user lookup
        admin_client = client_manager.get_admin_client()
        users_services = Users(client=admin_client)
        
        # Pull profile data via the Admin client using the session's user identity
        user_profile = users_services.get(user_id=session.userid)

        # 3. Apply your email verification security policy
        if not user_profile.emailverification:
            # Authenticate the user client explicitly with the new secret to destroy it safely
            user_client.set_session(session.secret)
            account_service.delete_session(session_id=session.id)

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Please verify your email before logging in."
            )
        
        # 4. Return standard structured token for OAuth2 consumers
        return {
            "access_token": session.secret,
            "token_type": "bearer",
            "user_id": session.userid,
            "expires_at": session.expire
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signin Failure: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication Failed: Invalid username or password"
        )
        