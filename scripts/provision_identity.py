"""Provision explicit verified OIDC subject bindings; no passwords or client-supplied roles."""

import argparse

from sqlalchemy import select

from larimia.config import get_settings
from larimia.marketplace.models import User
from larimia.marketplace.security import PERMISSIONS
from larimia.shared.audit import record_audit
from larimia.shared.db import SessionLocal

parser = argparse.ArgumentParser()
parser.add_argument("--issuer", required=True)
parser.add_argument("--subject", required=True)
parser.add_argument("--email", required=True)
parser.add_argument("--roles", required=True)
parser.add_argument("--operator", required=True)
args = parser.parse_args()
settings = get_settings()
roles = args.roles.split(",")
if not set(roles).issubset(PERMISSIONS):
    raise SystemExit("Unknown role")
workforce = any(role.lower() not in {"customer", "provider"} for role in roles)
expected = settings.workforce_oidc_issuer if workforce else settings.oidc_issuer
if not expected or args.issuer != expected:
    raise SystemExit("Issuer does not match configured identity authority for these roles")
with SessionLocal.begin() as db:
    user = db.scalar(select(User).where(User.subject == args.subject).with_for_update())
    if user and user.issuer != args.issuer:
        raise SystemExit("Existing subject belongs to another identity authority")
    if not user:
        user = User(subject=args.subject, issuer=args.issuer, email=args.email.lower(), roles=roles)
        db.add(user)
        db.flush()
    else:
        user.roles = roles
    record_audit(
        db,
        actor=args.operator,
        action="IdentityProvisioned",
        resource_type="user",
        resource_id=str(user.id),
        metadata={"issuer": args.issuer, "roles": roles},
    )
print("Identity binding provisioned and audited.")
