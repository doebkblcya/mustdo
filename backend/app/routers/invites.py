from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from app.deps import current_user, get_db
from app.schemas import InviteRedeemRequest, UserPublic
from app.services.invite_gate import redeem_invite


# Invite gate for the closed beta. Remove this router (and the invite-gate
# service) at public launch.
router = APIRouter(prefix="/api/invites", tags=["invites"])


@router.post("/redeem", response_model=UserPublic)
def redeem(
    payload: InviteRedeemRequest,
    db: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
):
    redeem_invite(db, int(user["id"]), payload.code)
    return UserPublic(id=int(user["id"]))
