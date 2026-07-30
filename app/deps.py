from .services.supabase_client import get_supabase_client


def get_client():
    return get_supabase_client()
