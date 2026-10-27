from fastapi import APIRouter

from app.api.v1 import auth, invitations, memberships, organizations

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(memberships.router)
api_router.include_router(invitations.router)
