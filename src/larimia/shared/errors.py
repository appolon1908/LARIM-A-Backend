from dataclasses import dataclass


@dataclass(frozen=True)
class DomainError(Exception):
    code: str
    message: str
    http_status: int = 400

    def __str__(self) -> str:
        return self.message


class ForbiddenError(DomainError):
    def __init__(self, code: str = "FORBIDDEN", message: str = "Action is not allowed"):
        super().__init__(code=code, message=message, http_status=403)


class ConflictError(DomainError):
    def __init__(self, code: str, message: str):
        super().__init__(code=code, message=message, http_status=409)


class NotFoundError(DomainError):
    def __init__(self, code: str, message: str):
        super().__init__(code=code, message=message, http_status=404)
