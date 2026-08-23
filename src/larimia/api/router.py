from fastapi import APIRouter

from larimia.api.routes.availability import router as availability
from larimia.api.routes.catalog import router as catalog
from larimia.api.routes.customers import router as customers
from larimia.api.routes.dispatch import router as dispatch
from larimia.api.routes.finance import router as finance
from larimia.api.routes.health import router as health
from larimia.api.routes.markets import router as markets
from larimia.api.routes.memberships import router as memberships
from larimia.api.routes.partners import router as partners
from larimia.api.routes.payments import router as payments
from larimia.api.routes.providers import router as providers
from larimia.api.routes.quotes import router as quotes
from larimia.api.routes.realtime import router as realtime
from larimia.api.routes.reviews import router as reviews
from larimia.api.routes.safety import router as safety
from larimia.api.routes.support import router as support
from larimia.api.routes.system import router as system
from larimia.api.routes.visits import router as visits
from larimia.api.routes.webhooks import router as webhooks
from larimia.bookings.api.routes import router as bookings

api_router = APIRouter()
api_router.include_router(health, prefix="/health", tags=["health"])
api_router.include_router(realtime, prefix="/ws", tags=["realtime"])
api_router.include_router(markets, prefix="/markets", tags=["markets"])
api_router.include_router(catalog, prefix="/catalog", tags=["catalog"])
api_router.include_router(providers, prefix="/providers", tags=["providers"])
api_router.include_router(quotes, prefix="/quotes", tags=["quotes"])
api_router.include_router(availability, prefix="/availability", tags=["availability"])
api_router.include_router(bookings, prefix="/bookings", tags=["bookings"])
api_router.include_router(dispatch, prefix="/dispatch", tags=["dispatch"])
api_router.include_router(visits, prefix="/visits", tags=["visits"])
api_router.include_router(payments, prefix="/payments", tags=["payments"])
api_router.include_router(safety, prefix="/safety", tags=["safety"])
api_router.include_router(partners, prefix="/partners", tags=["partners"])
api_router.include_router(memberships, prefix="/memberships", tags=["memberships"])
api_router.include_router(reviews, prefix="/reviews", tags=["reviews"])
api_router.include_router(support, prefix="/support", tags=["support"])
api_router.include_router(finance, prefix="/finance", tags=["finance"])
api_router.include_router(webhooks, prefix="/webhooks", tags=["webhooks"])

api_router.include_router(system, prefix="/system", tags=["system"])

api_router.include_router(customers, prefix="/customers", tags=["customers"])
