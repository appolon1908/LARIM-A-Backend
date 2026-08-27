from collections import Counter

from larimia.main import app


schema = app.openapi()
paths = schema.get("paths", {})
if not paths:
    raise SystemExit("OpenAPI schema contains no paths")

operation_ids: list[str] = []
for path, operations in paths.items():
    if not isinstance(operations, dict):
        continue
    for method, operation in operations.items():
        if method.lower() not in {
            "get",
            "post",
            "put",
            "patch",
            "delete",
            "options",
            "head",
        }:
            continue
        if not isinstance(operation, dict):
            raise SystemExit(
                f"Invalid OpenAPI operation at {method.upper()} {path}"
            )
        operation_id = operation.get("operationId")
        if not operation_id:
            raise SystemExit(
                f"Missing operationId at {method.upper()} {path}"
            )
        operation_ids.append(operation_id)

duplicates = [
    operation_id
    for operation_id, count in Counter(operation_ids).items()
    if count > 1
]
if duplicates:
    raise SystemExit(
        f"Duplicate OpenAPI operationIds: {sorted(duplicates)}"
    )

required_paths = {
    "/v1/health/live",
    "/v1/health/ready",
    "/v1/health/version",
    "/v1/system/capabilities",
    "/v1/availability",
    "/v1/quotes",
    "/v1/bookings",
    "/v1/bookings/from-quote/{quote_id}",
    "/v1/bookings/{booking_id}/confirm",
    "/v1/bookings/{booking_id}/cancel",
    "/v1/payments/authorize",
    "/v1/ws/tickets",
}
missing = sorted(required_paths.difference(paths))
if missing:
    raise SystemExit(
        f"OpenAPI is missing required marketplace paths: {missing}"
    )

print(
    f"validated {len(paths)} OpenAPI paths "
    f"and {len(operation_ids)} operations"
)
