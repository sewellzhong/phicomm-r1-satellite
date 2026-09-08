# R1 factory-audio agent

This is a self-owned, local-only privileged-agent skeleton. It contains no
vendor library, firmware, calibration, device node, SELinux policy, root tool,
or flashing command. The only implemented backend is `--fake`, which emits
synthetic silence for host tests. `--fake-frame-period-us` exists only to
accelerate soak-frame budgets in those tests. Omitting `--fake` fails closed with
`factory_backend_unimplemented`.

The production socket is `/dev/socket/r1_factory_audio`. The agent requires an
explicit `--expected-uid` and verifies each connection with `SO_PEERCRED`. The
init/SELinux ownership and the real dynamically loaded backend must be derived
from `r1-sample01` evidence after the R0 restore gate passes.

Host build and tests are run by `bash tools/factory_audio/check.sh`. An Android
API 22 ARMv7 build will be added to the same check once the pinned SDK/NDK is
available; the CMake project rejects other Android ABIs and newer API levels.
