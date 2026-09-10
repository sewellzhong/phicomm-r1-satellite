# R1 factory-audio agent

This is a self-owned, local-only privileged agent. It contains no vendor
library, firmware, calibration, root tool, or flashing command. The `--fake`
backend emits synthetic silence for host tests. `--fake-frame-period-us` exists
only to accelerate soak-frame budgets in those tests.

The production backend is selected only by an explicit `--vendor-library` plus
the proven input/output shape. It dynamically loads the library already present
on the device, follows the audited 3448 initialization sequence, disables vendor
debug recording, exposes DOA, and emits one 16 kHz S16LE mono channel. It rejects
playback-reference messages and reports AEC inactive until a real R1 test proves
the two hardware references and playback-source coverage. This prevents an
initialized library from being mistaken for a proven factory AEC chain.

The production socket is `/dev/socket/r1_factory_audio`. The agent requires an
explicit `--expected-uid`, uses mode `0660`, and verifies each connection with
`SO_PEERCRED`. The supplied init template binds the socket as root, changes its
group to the satellite UID, clears supplementary groups, and drops to the
Android `audio` UID/GID before loading the backend. The SELinux template defines
a dedicated domain without network or block-device access. It is staging input,
not a deployable policy: unresolved output-channel tokens and an incomplete R0
gate make the renderer fail closed.

Host build and tests are run by `bash tools/factory_audio/check.sh`. When the
pinned SDK/NDK is available, the same check builds Android API 22 ARMv7; the
CMake project rejects other Android ABIs and newer API levels. Vendor tests use
a self-owned mock shared library and never copy an R1 library into the build.

`tools/factory_audio/audit-offline-chain.py` separately verifies and extracts
the system partition from the private A/B image chunks, then audits a fixed
allowlist of factory-audio inputs. All extracted bytes and disassembly remain
under ignored private storage. The public reference records hashes and static
JNI facts only; a 4,800-byte original read buffer does not prove its runtime
channel layout and therefore cannot unlock the production backend.
