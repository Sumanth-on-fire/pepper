from fastapi import APIRouter, HTTPException, status

from app.models.signup import UserSignupModel
from app.services.supabase_client import get_supabase_client


router = APIRouter()

@router.post('/', status_code=status.HTTP_201_CREATED, tags=['Authentication'])
async def signup(user_data: UserSignupModel):
    try:
        # Build optional user metadata if provided
        options = {}
        if user_data.display_name:
            options["data"] = {"display_name": user_data.display_name}

        supabase = get_supabase_client().supabase
        # Request user creation from Supabase Auth
        response = supabase.auth.sign_up({
            "email": user_data.email,
            "password": user_data.password,
            "options": options if options else None
        })
        
        # Check if email confirmation is required by your Supabase settings
        user_confirmed = response.user.identities[0].identity_data.get("email_verified", False) if response.user.identities else False
        
        return {
            "message": "Registration successful!",
            "user_id": response.user.id,
            "email": response.user.email,
            "email_confirmed": user_confirmed,
            "detail": "Please check your inbox to confirm your account if required." if not user_confirmed else "Account ready to use."
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Registration failed: {str(e)}"
        )