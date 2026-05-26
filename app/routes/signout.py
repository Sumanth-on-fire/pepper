from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordBearer

from app.services.supabase_client import get_supabase_client

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='login')

@router.post("/signout", tags=['Authentication'])
async def signout(token: str= Depends(oauth2_scheme)):
    """
    Signs out the user globally and revokes their Supabase session tokens.
    """

    try:
        get_supabase_client().supabase.auth.set_session(token, "")
        get_supabase_client().supabase.sign_out()

        return {"message": "Signed out successfully"}
    
    except Exception as e:
        return {"error": str(e)}