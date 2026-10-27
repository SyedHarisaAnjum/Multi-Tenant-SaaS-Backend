"""Role policy shared by every service that manages people in an organization.

The rule is strict ranking: you may only act on members ranked *below* you, and only
grant roles ranked *below* your own. So admins manage members and viewers, owners
manage everyone else, and nobody can raise anyone (including themselves) to their own level.
"""

from app.core.exceptions import PermissionDeniedError
from app.db.models import Membership, MembershipRole

MANAGER_ROLES = frozenset({MembershipRole.OWNER, MembershipRole.ADMIN})


def ensure_can_manage(actor: Membership, role: MembershipRole) -> None:
    """Raise unless `actor` may manage someone holding, or grant, `role`."""
    if actor.role not in MANAGER_ROLES or not actor.role.outranks(role):
        raise PermissionDeniedError(
            f"Your role ({actor.role.value}) cannot manage the {role.value} role."
        )
