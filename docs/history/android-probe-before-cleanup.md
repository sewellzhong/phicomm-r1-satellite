> 2026-09-07 清理前快照，仅作历史证据。当前状态以根 README 为准。旧命令可能已停用。

# R1 Audio Probe

Minimal API 22 application used to verify that a Phicomm R1 can install,
upgrade, and start an independently named APK, then exercise its audio input
and output without replacing factory apps.

The application emits `R1_PROBE_READY` under the `R1Probe` Logcat tag when its
launcher activity starts. Audio diagnostics use `RECORD_AUDIO`; firmware 3448
also requires legacy `WRITE_EXTERNAL_STORAGE` for its physical FAT app-specific
directory. Code restricts diagnostic playback to that package-owned directory.

Version 42 packages the pinned pretrained Alexa microWakeWord v2 model.
Run `python3 tools/kws/prepare-alexa-microwakeword.py` from the repository root
before building. PCM remains S16LE, 16 kHz, mono, 20 ms frames.
The microWakeWord actions remain load/raw-score probes. AlexaListeningService
adds bounded foreground listening with detection events; alexa_engine_check
checks the real engine reset and frame contract using generated silence.
Start a 20-second no-retention microphone check from the repository root:

```bash
python3 tools/kws/run-r1-alexa-listen.py <adb-serial> --confirm-device r1-sample01 --seconds 20
```

The runner stops its service on exit. To stop a manually started session:

```bash
adb -s <adb-serial> shell am stopservice -n dev.sewellzhong.r1probe/.AlexaListeningService
```

Sessions last 5–3600 seconds and must be explicitly started. No boot receiver
or sticky restart is enabled. Do not run other audio probes concurrently.
See `docs/2026-09-05-alexa-pretrained.md` for validation boundaries.

Host tools:

- `tools/install-r1-probe.sh` validates the target and installs through the
  firmware-compatible package-manager entrypoint.
- `tools/run-r1-audio-probe.sh` captures all three required Android audio
  sources and tests a synthetic WAV.
- `tools/run-r1-audio-isolation-test.sh` temporarily isolates the factory audio
  packages and restores their foreground services with an exit trap.
- `tools/run-r1-audio-acceptance.sh` records per-source silence and controlled
  speech samples, plays an audible cue, and produces level comparisons.
- `tools/run-r1-audio-isolation-matrix.sh` tests the factory device and player
  packages separately and restores both packages after every run.
- `tools/run-r1-playback-route-probe.sh` records AK7755 mixer and AudioFlinger
  state before, during, and after a five-second playback diagnostic.
- `tools/play-r1-diagnostic-wav.sh` safely replays a WAV from `test-results/`
  with optional fixed gain for local intelligibility review.
- `tools/audit-r1-audio-provenance.sh` verifies the live 3448 system APKs,
  audio HAL, four-microphone libraries, and AK7755 data2 firmware against a
  pinned OTA reference without retaining pulled proprietary binaries.
- `tools/run-r1-capture-route-probe.sh` captures AudioFlinger, RK_MA4, AK7755,
  and route-property snapshots around one AudioRecord session.
- `tools/audit-r1-four-mic-interface.sh` records native exports and APK class
  references for the system-provided Unisound four-microphone path without
  retaining proprietary binaries.
- `tools/run-r1-four-mic-poc.sh` verifies the pinned system JNI and exposes a
  guarded capability/recording PoC. The capability probe passed on sample01,
  while recording is blocked by the normal app SELinux domain; the tool does
  not bundle the proprietary library or weaken that boundary.
- `tools/run-r1-stereo-channel-probe.sh` records diagnostic stereo input and
  derives left, right, average, and difference mono WAVs to detect weak-channel
  selection or phase cancellation. It does not change the production format.
- `tools/compare-stereo-channels.py` reports per-channel RMS and Pearson
  correlation for a 16 kHz stereo diagnostic WAV.
- `tools/spectral-denoise-wav.py` provides a dependency-free offline STFT
  spectral-subtraction reference; `tools/run-r1-offline-processing-ab.sh`
  evaluates fixed gentle, balanced, and strong profiles before any real-time
  integration.
- `tools/adaptive-gain-wav.py` applies 20 ms activity-gated, peak-limited gain;
  `tools/run-r1-offline-adaptive-gain.sh` evaluates it after the balanced
  denoiser without counting gain alone as signal-separation improvement.
- `tools/run-r1-processing-benchmark.sh` runs the Java port against the pinned
  real-device WAV on R1 and compares it with the Python reference while
  recording elapsed time and PSS; it does not connect the processor to the mic.
- `tools/run-r1-streaming-processing-probe.sh` performs fixed-size noise
  calibration and bounded incremental STFT processing directly from
  AudioRecord, then records timing, PSS, read, overrun, and recovery evidence.
- `tools/run-r1-streaming-soak.sh` runs the same bounded processor for 30
  minutes without retaining audio, samples PSS/PID/AudioFlinger every minute,
  captures app GC logs, applies fixed acceptance checks, and restores the
  temporarily stopped audio packages on every exit path. Add `--smoke` for a
  20-second no-retention regression before the formal run.
- `tools/run-r1-processed-speech-acceptance.sh` captures raw and processed
  output from the same VOICE_COMMUNICATION reads, with an internally timed cue
  for controlled 1 m speech comparison. Device copies are removed after pull.
- `tools/manage-r1-app-layer.sh` reports app-layer state and provides guarded,
  reversible disable/restore actions; it never uninstalls packages.

Build with the pinned wrapper and JDK 17:

```bash
export ANDROID_SDK_ROOT="$HOME/.local/share/android-sdk"
export JAVA_HOME="$HOME/.sdkman/candidates/java/17.0.19-tem"
./gradlew --no-daemon testDebugUnitTest lintDebug assembleDebug
```

The APK exposes `four_mic_capabilities` and `four_mic_record` diagnostics. The
JNI declaration mirrors firmware 3448 only; no native library is packaged in
the APK. Run the safe capability check with:

```bash
tools/run-r1-four-mic-poc.sh <adb-serial> capabilities --confirm-device r1-sample01
```

The recording mode additionally requires `--confirm-temporary-disable` and
refuses to proceed unless Package Manager confirms both audio overlays really
entered the disabled-user state.

Human test with a start tone and two end tones (90 seconds; temporary audio
overlay isolation, automatically restored):

```bash
bash tools/kws/run-r1-alexa-isolated.sh <adb-serial> --confirm-device r1-sample01 --human-test
```

Wait two seconds after the start tone for model warmup, then speak. The tones
use generated PCM through the existing API 22 playback path, outside microphone
capture; temporary generated WAVs are deleted. No microphone recording is saved.
Playback completion in logs must still be confirmed as audible by the user.

Version 34 uses a 0.8-second start tone and two 0.5-second end tones separated
by 0.3 seconds. A short check requires no speech:

```bash
bash tools/kws/run-r1-alexa-isolated.sh <adb-serial> --confirm-device r1-sample01 --cue-check
```


The user selected pretrained Alexa and stopped further KWS training/acoustic
tests. Legacy candidate tools and downloaded training environments were removed.
Version 35 adds the `assist/` protocol foundation (HA Core 2026.8.2, OkHttp 4.12.0).
It is not yet connected to the microphone/playback service, and this build has
not been deployed to R1. No credential is bundled or persisted.


Version 36 integrates the explicit AssistRuntimeService. Provision it with
`tools/assist/run-r1-assist.py`; authentication-only is the default and no token
is persisted. See `docs/2026-09-05-assist-runtime.md` for the actual verification
scope, HTTPS trust-root source and optional listening mode.

Version 37 adds bounded content-free event history and PCM/KWS counters to the control status. The host launcher prints events and a 10-second audio heartbeat; no spoken text or recordings are logged.

Version 38 runs STT separately, removes only the leading Alexa wake word in memory, then starts intent-to-TTS. Host regression checks pass; the user reports a successful HassGetCurrentTime result after this fix. Audible playback of this particular time reply has not been explicitly confirmed.

Version 39 uploads only 200 ms of pre-roll, disables HA endpoint VAD and uses an 8-second minimum / 1.5-second quiet tail / 20-second maximum client command window. Two user-reported leading wake-word spellings are handled explicitly. 52 host tests pass; acoustic effectiveness is unverified and short commands incur the minimum window delay.

Version 40 supersedes the version38/39 text stripping and minimum-window behavior: ten user-selected local acknowledgements (six daily, four occasional), microphone released during prompt, fresh recording afterwards, six seconds to start speaking, WebRTC VAD trailing quiet of 1.2 seconds, 20-second command cap. No HA run is started on no-speech timeout. 50 host tests and native API22 synthetic-silence smoke pass; full acoustic behavior is unverified.

Version 41 discards STT results containing no Unicode letters or digits before intent/TTS. A reported punctuation-only response is covered by regression tests, including successful processing of the next command. 55 host tests pass; real-device silent behavior after this fix is unverified.

Version 42 uses CommandInputPolicy for layered no-input handling: conservative lexical/marker checks, explicit cancellation, follow-up-aware fillers/wake-only text, acoustic evidence for prompt echo/repetition, and silent handling of HA stt-no-text-recognized. Genuine errors still surface. Diagnostic output contains only reason enums and voiced duration. See docs/2026-09-05-assist-input-policy.md.
