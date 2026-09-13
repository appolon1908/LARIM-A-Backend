from openapi_spec_validator import validate

from larimia.main import app


def test_openapi_valid_and_operation_ids_unique():
    schema = app.openapi()
    validate(schema)
    operations = [
        operation
        for path in schema["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    ids = [operation["operationId"] for operation in operations]
    assert len(ids) == len(set(ids))
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


def test_frontend_critical_contract_and_authentication():
    schema = app.openapi()
    for path in [
        "/api/v1/bookings",
        "/api/v1/provider/offers",
        "/api/v1/admin/payments",
        "/api/v1/admin/audit",
    ]:
        assert schema["paths"][path]["get"]["security"] == [{"HTTPBearer": []}]
    booking = schema["components"]["schemas"]["BookingOutput"]["properties"]
    assert {"id", "bookingNumber", "scheduledStart", "total", "status", "version"}.issubset(booking)
    assert "Idempotency-Key" in {
        parameter["name"] for parameter in schema["paths"]["/api/v1/bookings"]["post"]["parameters"]
    }
