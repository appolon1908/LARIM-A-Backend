# ADR-003: Transactional Outbox and Inbox

## Status
Accepted

## Decision

All domain changes that trigger asynchronous work persist outbox events in the same PostgreSQL transaction. All external webhooks pass through a persistent deduplicated inbox.

## Why

Directly updating a database and then publishing an external message can create split-brain state when either step fails.

## Consequence

Workers must be idempotent and replay-safe.
