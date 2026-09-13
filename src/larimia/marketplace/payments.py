"""Payment vendor interface. Local simulation cannot move real funds."""

import hashlib
from typing import Protocol


class PaymentGateway(Protocol):
    def authorize(self, reference: str, amount: int, currency: str, token: str) -> str: ...
    def capture(self, reference: str, amount: int) -> str: ...
    def cancel(self, reference: str) -> str: ...
    def refund(self, reference: str, amount: int) -> str: ...


class MockGateway:
    @staticmethod
    def _reference(reference: str) -> str:
        return "mock_" + hashlib.sha256(reference.encode()).hexdigest()[:32]

    def authorize(self, reference: str, amount: int, currency: str, token: str) -> str:
        if token == "mock_declined":
            raise ValueError("Payment authorization declined")
        if token != "mock_success" or amount <= 0:
            raise ValueError("Only explicit mock payment tokens are accepted")
        return self._reference(reference)

    def capture(self, reference: str, amount: int) -> str:
        return self._reference("capture:" + reference)

    def cancel(self, reference: str) -> str:
        return self._reference("cancel:" + reference)

    def refund(self, reference: str, amount: int) -> str:
        return self._reference("refund:" + reference)
