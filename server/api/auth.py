from uuid import UUID
import jwt
from fastapi import Header
from server.repositories.postgres import DomainError

class SessionVerifier:
    def __init__(self, settings):
        self.issuer = settings.supabase_url + '/auth/v1'
        self.audience = settings.audience
        self.keys = jwt.PyJWKClient(self.issuer + '/.well-known/jwks.json', timeout=10)

    def __call__(self, authorization: str | None = Header(default=None)) -> UUID:
        try:
            if not authorization or not authorization.startswith('Bearer '):
                raise ValueError('missing bearer')
            token = authorization[7:]
            key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(token,key.key,algorithms=['ES256','RS256'],
                                audience=self.audience,issuer=self.issuer,
                                options={'require':['exp','iss','aud','sub']})
            return UUID(claims['sub'])
        except (jwt.PyJWTError, ValueError, KeyError):
            raise DomainError(401,'unauthorized','A valid Supabase session is required') from None
