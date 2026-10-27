import enum
import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class MembershipRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]

    def outranks(self, other: "MembershipRole") -> bool:
        return self.rank > other.rank


_ROLE_RANK = {
    MembershipRole.OWNER: 3,
    MembershipRole.ADMIN: 2,
    MembershipRole.MEMBER: 1,
    MembershipRole.VIEWER: 0,
}


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        # Exactly one owner per organization; ownership moves only via transfer.
        Index(
            "uq_memberships_one_owner_per_org",
            "organization_id",
            unique=True,
            postgresql_where=text("role = 'owner'"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # The unique constraint above indexes organization_id first; this covers
    # "which organizations does this user belong to".
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MembershipRole] = mapped_column(
        str_enum(MembershipRole, "membership_role"),
        nullable=False,
        default=MembershipRole.MEMBER,
    )
