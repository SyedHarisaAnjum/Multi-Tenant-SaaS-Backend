import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin, str_enum
from app.db.models.organization import MembershipRole


class Invitation(UUIDPrimaryKeyMixin, Base):
    """A single-use invitation to join an organization. Only the token's hash is stored.

    State is derived from timestamps: pending until accepted_at or revoked_at is set,
    or expires_at passes.
    """

    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint("email = lower(btrim(email))", name="email_normalized"),
        # Ownership is only ever transferred, never granted by invitation.
        CheckConstraint("role <> 'owner'", name="role_not_owner"),
        CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL", name="not_both_accepted_and_revoked"
        ),
        # At most one open invitation per email per organization.
        Index(
            "uq_invitations_pending_org_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[MembershipRole] = mapped_column(
        str_enum(MembershipRole, "invitation_role"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
