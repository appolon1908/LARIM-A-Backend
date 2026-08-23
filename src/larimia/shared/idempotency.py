from fastapi import Header, HTTPException


def require_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    if not idempotency_key or len(idempotency_key) < 8:
        raise HTTPException(status_code=400, detail={"code": "IDEMPOTENCY_KEY_REQUIRED"})
    return idempotency_key
