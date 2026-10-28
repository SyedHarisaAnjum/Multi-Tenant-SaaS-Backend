from fastapi import APIRouter

from app.api.v1 import (
    auth,
    invitations,
    memberships,
    organizations,
    projects,
    tasks,
    workspaces,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(memberships.router)
api_router.include_router(invitations.router)
api_router.include_router(workspaces.router)
api_router.include_router(projects.router)
api_router.include_router(tasks.router)
