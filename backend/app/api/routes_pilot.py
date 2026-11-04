"""Pilot requests from the public site.

Anyone may submit; only a signed-in operator may read them. A hidden field catches
simple bots, and submissions are limited per sender and site-wide per hour. The
sender's address is stored only as a salted hash, used for those limits.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.auth.roles import OPERATOR_ALWAYS
from app.config import settings
from app.db.models import PilotRequest
from app.deps import get_db
from app.demo_guard import HourlyBudget

router = APIRouter(prefix="/pilot-requests", tags=["pilot requests"])
_limits = HourlyBudget()
PER_SENDER_PER_HOUR = 5
SITE_WIDE_PER_HOUR = 60
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")


class PilotRequestIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=6, max_length=254)
    organisation: str = Field(min_length=2, max_length=160)
    role: Optional[str] = Field(None, max_length=120)
    site_type: Literal["pharma", "logistics", "manufacturing", "healthcare", "other"]
    fleet_size: Optional[Literal["planning", "1-5", "6-20", "21-100", "100+"]] = None
    message: Optional[str] = Field(None, max_length=2000)
    consent: bool
    website: Optional[str] = Field(None, max_length=200)   # hidden from people; bots fill it in

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if not EMAIL.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("name", "organisation", "role", "message")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


def _sender_hash(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    addr = fwd or (request.client.host if request.client else "unknown")
    return hashlib.sha256((settings.jwt_secret + "|pilot|" + addr).encode()).hexdigest()[:32]


@router.post("")
def submit(body: PilotRequestIn, request: Request, db: Session = Depends(get_db)):
    if not body.consent:
        raise HTTPException(422, "Please agree to be contacted about this request")
    reference = "PR-" + secrets.token_hex(3).upper()
    if body.website:   # bot: answer as if accepted, store nothing
        return {"ok": True, "reference": reference}
    sender = _sender_hash(request)
    for key, limit in ((f"sender:{sender}", PER_SENDER_PER_HOUR), ("all", SITE_WIDE_PER_HOUR)):
        wait = _limits.take(key, limit)
        if wait:
            raise HTTPException(429, "Too many requests. Please try again later.", headers={"Retry-After": str(wait)})
    db.add(PilotRequest(reference=reference, created_at=dt.datetime.now(dt.timezone.utc), name=body.name, email=body.email,
                        organisation=body.organisation, role=body.role or None, site_type=body.site_type,
                        fleet_size=body.fleet_size, message=body.message or None, source_hash=sender))
    db.commit()
    return {"ok": True, "reference": reference}


@router.get("")
def list_requests(limit: int = 100, user=Depends(OPERATOR_ALWAYS), db: Session = Depends(get_db)):
    rows = db.query(PilotRequest).order_by(PilotRequest.created_at.desc()).limit(max(1, min(limit, 500))).all()
    return [{"reference": r.reference, "created_at": r.created_at.isoformat(), "name": r.name, "email": r.email,
             "organisation": r.organisation, "role": r.role, "site_type": r.site_type, "fleet_size": r.fleet_size,
             "message": r.message} for r in rows]
