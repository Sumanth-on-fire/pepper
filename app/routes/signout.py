from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.services.supabase_client import get_supabase_client
from appwrite.services.account import Account
from app.services.appwrite_client import client_manager

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='login')

def get_current_session_token(token: str = Depends(oauth2_scheme)) -> str:
    """
    Validates that a token exists in the request. 
    It passes the token down for explicit execution validation against Appwrite.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please sign in first."
        )
    return token

@router.post("/", tags=['Authentication'])
async def signout(token: str = Depends(get_current_session_token)):
    try:
        # Generate a user client dedicated solely to this active token instance
        user_client = client_manager.get_user_client(session_token=token)
        account_service = Account(user_client)
        
        # Destroys the active session server-side on Appwrite nodes
        account_service.delete_session(session_id='current')
        
        return {
            "status": "success",
            "message": "Successfully signed out. Session token invalidated."
        }
        
    except Exception as e:
        logger.error(f"Signout Failure: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to sign out. The session may already be dead or invalid."
        )