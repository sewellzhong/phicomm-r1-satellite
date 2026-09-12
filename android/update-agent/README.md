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

This commit does **not** yet ship a root daemon, package-manager transport, or a
deployable SELinux policy. Those pieces require a separate init service with an
exact peer UID, a private root-owned backup directory, no network or block
access, and real firmware-3448 AVC/package-manager evidence. Until then, the
state machine is host-validated groundwork and is not an OTA or R1 result.
