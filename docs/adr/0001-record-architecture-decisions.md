# 1. Record architecture decisions

Date: 2026-07-21

## Status

Accepted

## Context

We need to record the architectural decisions made on this project, both so that future
contributors understand *why* the code looks the way it does, and so that the reasoning is
auditable rather than tribal.

## Decision

We will use Architecture Decision Records, as described by Michael Nygard, stored as numbered
Markdown files under `docs/adr/`. Each record captures Context, Decision, and Consequences and
is immutable once accepted; a superseding decision gets a new record.

## Consequences

- Decisions are discoverable and reviewable in the same pull-request flow as code.
- The next engineer (or agent) can reconstruct intent without archaeology.
- Superseded decisions remain in history rather than being edited away.
