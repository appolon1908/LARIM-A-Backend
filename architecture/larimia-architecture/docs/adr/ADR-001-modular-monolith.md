# ADR-001: Start as a Modular Monolith

## Status
Accepted

## Decision

Build LARIMÍA as a domain-driven modular monolith with separate worker processes.

## Why

Booking, assignment, payment, ledger, cancellation, and recovery frequently require strong transactional consistency. Early microservices would introduce distributed transactions and operational complexity before scale requires them.

## Consequences

Positive:
- simpler transactions
- fewer failure modes
- easier local development
- lower infrastructure cost
- faster MVP delivery

Negative:
- requires strict internal module discipline
- scaling is initially coarse-grained

## Extraction Rule

A domain becomes an independent service only when at least one is true:
- independently scaling workload is demonstrated,
- different release ownership is necessary,
- failure isolation provides measurable value,
- regulatory isolation requires it.
