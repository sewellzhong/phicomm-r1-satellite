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

Protocol version 1 uses AF_UNIX SOCK_SEQPACKET with fixed-size, network-byte-order
apply, health, and response frames. The listener refuses an existing path or a
replaceable parent, creates a mode-0600 node for the configured satellite UID,
then checks the kernel SO_PEERCRED UID exactly. Apply accepts exactly one
SCM_RIGHTS descriptor and dispatches bounded staging into `PackageOrchestrator`;
health accepts none. Connections have bounded send/receive timeouts, malformed
ancillary data is closed and rejected, and every well-formed request gets an
explicit success or failure response.

The API-22 APK now bundles a small JNI client for the fixed
`/dev/socket/r1_update_supervisor` endpoint. A root/shell-only local maintenance
request names an operation whose APK is already in the app-private update
inbox; Java verifies the bounded file and SHA-256 before JNI sends its read-only
descriptor. Apply is deliberately send-only because Android may kill the old
APK before an install response can return. `MY_PACKAGE_REPLACED` records a
same-boot marker and starts a bounded health reporter. It probes all four gates
and sends nothing until all are true; a reboot clears the marker instead of
converting a post-reboot start into health.

`run_update_supervisor` now supplies the long-running accept/tick/recovery loop
around an already secured listener. It isolates malformed clients, polls health
deadlines, and persists the kernel boot UUID before package replacement so a
recovered health window can reject another boot. Transaction v2 adds that boot
identity while retaining fail-closed v1 reads. A host-only executable and fake
package backend exercise malformed-client isolation followed by cross-process
apply and health confirmation; they are test artifacts, not a device backend.

This directory still does **not** ship a device root daemon executable, a real
Android PackageManager implementation, init service, or deployable SELinux
policy. There is no authenticated remote candidate delivery path yet; the
app-private inbox is a maintenance boundary, not OTA download support. Device
deployment still requires a root-owned non-writable socket parent, no network
or block access, and real firmware-3448 AVC/package-manager evidence. Until
then, this is host-validated groundwork and is not an OTA or R1 result.
