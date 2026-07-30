from pydantic import BaseModel, EmailStr, Field


class UserSignupModel(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, description="Password must be at least 6 characters long")
    display_name: str | None = None
    username: str | None = None  
    