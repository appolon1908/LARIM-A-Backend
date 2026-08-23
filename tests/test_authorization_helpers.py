from fastapi import HTTPException

from larimia.shared.auth import Principal, Role
from larimia.shared.authorization import require_market


def test_market_claim_blocks_other_market():
    p = Principal(
        subject="u",
        issuer="i",
        roles=frozenset({Role.DISPATCHER}),
        market_codes=frozenset({"DO-SDQ"}),
    )
    require_market(p, "DO-SDQ")
    try:
        require_market(p, "DO-PUJ")
        raise AssertionError()
    except HTTPException as exc:
        assert exc.status_code == 403
