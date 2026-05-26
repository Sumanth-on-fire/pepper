from fastapi import APIRouter, Depends, HTTPException,status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from app.services.supabase_client import get_supabase_client

router = APIRouter()

@router.post("/", tags=['Authentication'])
async def signin(form_data: OAuth2PasswordRequestForm = Depends()):
    """
     Logs in a user via supabase and returns access/refresh tokens
    """

    try:
        response = get_supabase_client().supabase.auth.sign_in_with_password({
            "email": form_data.username,
            "password": form_data.password
        })

        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "token_type": "bearer"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail=f"Invalid Credentials or unconfirmed account: {str(e)}"
        )

    