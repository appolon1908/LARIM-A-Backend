class PaymentProviderError(RuntimeError):
    """Safe, normalized provider failure.

    Provider payloads are intentionally not placed in the exception message so
    credentials, client secrets, PII and processor internals do not leak into
    API responses or logs.
    """

    def __init__(
        self,
        code: str,
        message: str = "Payment provider request failed",
        *,
        retryable: bool = False,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.http_status = http_status
