# ADR-002: PostgreSQL Is Transactional Authority

## Status
Accepted

## Decision

PostgreSQL/PostGIS is the authoritative store for bookings, availability commitments, assignments, money, audit events, and market configuration.

Redis is limited to cache, throttling, ephemeral holds, and coordination.

## Why

The platform must never lose or contradict:
- booking ownership,
- provider schedule,
- payment state,
- ledger state.

## Consequence

All business-critical transitions commit through PostgreSQL transactions.
