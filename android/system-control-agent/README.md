# R1 system-control agent

This is a device-limited privileged bridge for `r1-sample01` firmware 3448. It
is intentionally separate from the update supervisor and factory-audio agent.

The only protocol operations are:

- set both fixed firmware LED brightness nodes to levels 0 through 4 and return
  their immediate readback;
- reboot the whole device, with no reason, command, path, or shell argument.

Requests and responses are exactly eight-byte `SOCK_SEQPACKET` records. The init
socket is mode 0600 for UID 10010 and every accepted connection is independently
checked with `SO_PEERCRED`. The enforcing SELinux domain has no network, block
device, package-manager, shell, filesystem-path selection, or update permission.

Build the ARMv7/API 22 agent and APK JNI client with:

```sh
ANDROID_SDK_ROOT=/path/to/sdk bash tools/build-r1-system-control.sh
```

The files under `device/` are policy and init inputs for an audited boot-only
increment. They are not independently deployable and must pass the project's
device identity, dual-read, immutable candidate, single-write, and full-readback
gates.
