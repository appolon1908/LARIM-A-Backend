# Git Review

Suggested commit:

```text
feat: production review candidate architecture and marketplace primitives
```

Recommended review order:

1. `src/larimia/config.py`
2. `src/larimia/shared/auth.py`
3. `src/larimia/shared/command_context.py`
4. `src/larimia/shared/idempotency_*`
5. `src/larimia/shared/events.py`
6. `src/larimia/adapters/contracts.py`
7. `src/larimia/bookings/`
8. `src/larimia/api/router.py`
9. `docs/API-MATRIX.md`
10. `docs/PRODUCTION-GATES.md`
11. `docs/IMPLEMENTATION-STATUS.md`
