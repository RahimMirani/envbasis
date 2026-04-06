from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.invitation import InvitationDetail, InvitationSummary
from app.schemas.member import ProjectMemberRead
from app.services.invitation_service import (
    accept_invitation,
    get_invitation_by_token_for_user,
    list_invitations_for_user,
    reject_invitation,
)

router = APIRouter(prefix="/me")


@router.get("/invitations", response_model=list[InvitationSummary])
def get_my_invitations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[InvitationSummary]:
    return list_invitations_for_user(db, user=current_user)


@router.get("/invitations/by-token/{token}", response_model=InvitationDetail)
def get_my_invitation_by_token(
    token: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvitationDetail:
    return get_invitation_by_token_for_user(db, user=current_user, raw_token=token)


@router.post(
    "/invitations/{invitation_id}/accept",
    response_model=ProjectMemberRead,
    status_code=status.HTTP_200_OK,
)
def accept_my_invitation(
    invitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectMemberRead:
    return accept_invitation(db, user=current_user, invitation_id=invitation_id)


@router.post("/invitations/{invitation_id}/reject", response_model=MessageResponse)
def reject_my_invitation(
    invitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    reject_invitation(db, user=current_user, invitation_id=invitation_id)
    return MessageResponse(detail="Invitation declined.")
