from typing import Mapping, Protocol


class IdentityProvider(Protocol):
    async def verify_identity(self, *, person_id: str, payload: dict) -> dict: ...


class CrmProvider(Protocol):
    async def upsert_customer(self, *, customer: dict) -> str: ...

    async def upsert_provider(self, *, provider: dict) -> str: ...


class EmailProvider(Protocol):
    async def send(self, *, to: str, template: str, data: dict) -> str: ...


class SmsProvider(Protocol):
    async def send(self, *, to: str, template: str, data: dict) -> str: ...


class WorkflowProvider(Protocol):
    async def trigger(self, *, workflow_code: str, payload: dict) -> str: ...


class ObjectStorage(Protocol):
    async def create_upload(self, *, object_key: str, content_type: str) -> dict: ...

    async def create_download(self, *, object_key: str) -> str: ...


class MalwareScanner(Protocol):
    async def scan(self, *, object_key: str) -> str: ...


class Geocoder(Protocol):
    async def geocode(self, *, address: str, country_code: str) -> dict: ...

    async def travel_time(
        self,
        *,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> int: ...


class PaymentProvider(Protocol):
    code: str

    async def create_checkout(
        self,
        *,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        reference: dict,
    ) -> dict: ...

    async def authorize(
        self,
        *,
        token: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        reference: dict,
    ) -> dict: ...

    async def capture(
        self,
        *,
        external_id: str,
        amount_minor: int | None,
        currency: str,
        idempotency_key: str,
    ) -> dict: ...

    async def void(
        self,
        *,
        external_id: str,
        idempotency_key: str,
    ) -> dict: ...

    async def refund(
        self,
        *,
        external_id: str,
        amount_minor: int,
        currency: str,
        reason: str,
        idempotency_key: str,
    ) -> dict: ...

    async def verify_webhook(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> dict: ...

    def translate_webhook(self, payload: dict) -> dict: ...


class PayoutProvider(Protocol):
    code: str

    async def create_payout(
        self,
        *,
        provider_ref: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
    ) -> dict: ...


class BusinessVerificationProvider(Protocol):
    async def verify_business(
        self,
        *,
        legal_name: str,
        country_code: str,
        registration_number: str | None,
    ) -> dict: ...


class CreditDataProvider(Protocol):
    async def assess(
        self,
        *,
        subject_ref: str,
        purpose: str,
        consent_ref: str,
    ) -> dict: ...


class AnalyticsSink(Protocol):
    async def publish(self, *, event_name: str, payload: dict) -> None: ...
