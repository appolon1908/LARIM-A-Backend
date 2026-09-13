from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_markets():
    return {
        "markets": [
            {
                "code": "DO-SDQ",
                "currency": "DOP",
                "timezone": "America/Santo_Domingo",
                "active": True,
            },
            {
                "code": "DO-PUJ",
                "currency": "DOP",
                "timezone": "America/Santo_Domingo",
                "active": False,
            },
            {
                "code": "DO-STI",
                "currency": "DOP",
                "timezone": "America/Santo_Domingo",
                "active": False,
            },
        ]
    }
