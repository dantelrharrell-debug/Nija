# Concurrent authority-marker publication repair

Production error observed after the owner merged PR #2979:
`No such file or directory: data/authority_heartbeat.flag.tmp -> data/authority_heartbeat.flag`.
The installed v169 heartbeat wrapper publishes this authority-liveness marker
using a fixed temporary filename. Two concurrent/detached heartbeat writers can
consume the same temporary file. This is separate from confirmed execution proof.

Replace only v169's atomic JSON writer with a unique sibling temporary file for
each publication, followed by the same atomic Path.replace. Failed writes still
raise and preserve the previous marker; temporary files are cleaned up. Payloads,
marker paths, provenance, freshness, generation and every authority/activation
check remain unchanged. This does not make an authority marker qualify as a
trade/fill, grant writer authority, fix broker open-position failures, or certify
live readiness. Do not inject ACCOUNT_BALANCE or manufacture execution proof.

The old writer deterministically reproduces FileNotFoundError when two writes
are synchronized at publication. Three new tests verify successful concurrent
publication, replacement-failure preservation/propagation, and serialization
failure cleanup. All seven existing v169 integrity tests also pass, including
rejection of authority-generated fill proof and preservation of execution markers.
Syntax and secret checks passed; focused CodeQL results are documented in the PR.
The CI suite must pass and AGENTS.md requires human review before merging a
writer/authority-heartbeat change. No strategy logic or position sizing changed.
