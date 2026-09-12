# R1 update supervisor

This directory owns the fail-closed state machine for the future device-side
update supervisor. It is deliberately separate from the satellite APK and the
factory-audio agent: a candidate that crashes cannot be trusted to roll itself
back, while the audio agent permanently drops root before accepting clients.

The policy accepts only the fixed production package, a strictly increasing
version, a bounded APK, an explicit SHA-256, and the same signer digest as the
installed package. After replacement it independently rechecks package,
version, bytes, and signer. Health requires the service, persistent state,
factory-audio agent, and original-package isolation boundary. Timeout,
supervisor restart during installation, reboot before health, identity drift,
or partial health all enter rollback. A rollback is complete only after the old
version and signer are read back.

The host runtime adds an exact-UID admission primitive, an owner-only transaction
store using fsync plus atomic rename, crash recovery into rollback, and bounded
APK staging from a regular-file descriptor. APK names are derived from the
validated operation id; callers cannot ask the supervisor to open a path.
Staged bytes are published without replacing an existing archive only after
exact size and SHA-256 verification.

`PackageOrchestrator` connects the durable controller to a typed, replaceable
package backend. It independently reads the current and candidate identities,
backs up and re-reads the old package, persists `installing`, replaces the
package, and reads the result again before waiting for all four health signals.
Every failure transition must be durable before downgrade is invoked. A host
fake verifies success, backup rejection, install and identity failures, health
failure, interrupted-install recovery, rollback failure, and persistence
failure without executing shell text.

This directory still does **not** ship a listening root daemon, a real Android
PackageManager implementation, satellite-side request/health client, init
service, or deployable SELinux policy. Those pieces require a private local
socket with SO_PEERCRED wired to the exact app UID, a root-owned backup
directory, no network or block access, and real firmware-3448
AVC/package-manager evidence. Until then, this is host-validated groundwork and
is not an OTA or R1 result.
