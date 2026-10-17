"""Server-only configuration. Never serialize these settings to the browser."""
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str
    supabase_url: str
    service_key: str
    audience: str = 'authenticated'
    bucket: str = 'journal-media'
    public_url: str = 'http://localhost:8000'
    pipeline_version: str = 'analysis-v4'

    @classmethod
    def load(cls):
        return cls(os.environ['DATABASE_URL'], os.environ['SUPABASE_URL'].rstrip('/'),
                   os.environ['SUPABASE_SERVICE_ROLE_KEY'],
                   os.getenv('SUPABASE_JWT_AUDIENCE', 'authenticated'),
                   os.getenv('MEDIA_BUCKET', 'journal-media'),
                   os.getenv('API_PUBLIC_URL', 'http://localhost:8000').rstrip('/'),
                   os.getenv('PIPELINE_VERSION', 'analysis-v4'))
