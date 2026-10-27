import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import ensure_can_manage
from app.db.models import Membership, MembershipRole, User
from app.repositories.activity_log_repository import ActivityLogRepository
from app.repositories.membership_repository import MembershipRepository


class MembershipService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.memberships = MembershipRepository(db)
        self.activity = ActivityLogRepository(db)

    def list_members(self, organization_id: uuid.UUID) -> list[tuple[Membership, User]]:
        return self.memberships.list_with_users(organization_id)

    def change_role(
        self, actor: Membership, target_user_id: uuid.UUID, new_role: MembershipRole
    ) -> Membership:
        if target_user_id == actor.user_id:
            raise PermissionDeniedError("You can't change your own role.")
        target = self._get_target_for_update(actor, target_user_id)
        ensure_can_manage(actor, target.role)  # can't touch peers or superiors
        ensure_can_manage(actor, new_role)  # can't grant your own level or above

        old_role = target.role
        if old_role is new_role:
            return target
        target.role = new_role
        self.activity.record(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            action="member.role_changed",
            entity_type="membership",
            entity_id=target.id,
            details={"user_id": str(target_user_id), "from": old_role.value, "to": new_role.value},
        )
        self.db.commit()
        return target

    def remove(self, actor: Membership, target_user_id: uuid.UUID) -> None:
        """Remove a member, or leave the organization when target is the actor."""
        target = self._get_target_for_update(actor, target_user_id)
        if target.role is MembershipRole.OWNER:
            raise PermissionDeniedError("The owner can't be removed. Transfer ownership first.")
        leaving = target.user_id == actor.user_id
        if not leaving:
            ensure_can_manage(actor, target.role)

        self.activity.record(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            action="member.left" if leaving else "member.removed",
            entity_type="membership",
            entity_id=target.id,
            details={"user_id": str(target_user_id), "role": target.role.value},
        )
        self.memberships.delete(target)
        self.db.commit()

    def transfer_ownership(self, actor: Membership, new_owner_user_id: uuid.UUID) -> None:
        if new_owner_user_id == actor.user_id:
            raise ConflictError("You already own this organization.")
        # Re-read the caller's row under lock: the role check must hold at commit time.
        current_owner = self.memberships.get_for_update(actor.organization_id, actor.user_id)
        if current_owner is None or current_owner.role is not MembershipRole.OWNER:
            raise PermissionDeniedError("Only the owner can transfer ownership.")
        new_owner = self._get_target_for_update(actor, new_owner_user_id)

        # Demote first: the one-owner-per-org unique index rejects two owners at once.
        current_owner.role = MembershipRole.ADMIN
        self.db.flush()
        new_owner.role = MembershipRole.OWNER
        self.activity.record(
            organization_id=actor.organization_id,
            actor_id=actor.user_id,
            action="organization.ownership_transferred",
            entity_type="organization",
            entity_id=actor.organization_id,
            details={"from": str(actor.user_id), "to": str(new_owner_user_id)},
        )
        self.db.commit()

    def _get_target_for_update(self, actor: Membership, user_id: uuid.UUID) -> Membership:
        target = self.memberships.get_for_update(actor.organization_id, user_id)
        if target is None:
            raise NotFoundError("Member not found.")
        return target
