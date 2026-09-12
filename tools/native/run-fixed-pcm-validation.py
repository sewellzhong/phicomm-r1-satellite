#!/usr/bin/env python3
"""Drive one bounded real Assist run with fixed PCM over the shell-only control socket."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path
import time
import wave

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("native_admin", HERE / "manage-r1-native.py")
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)


def load_pcm(path):
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
            raise RuntimeError("fixed_pcm_format_required")
        pcm = source.readframes(source.getnframes())
    if not pcm or len(pcm) > 320000:
        raise RuntimeError("fixed_pcm_duration_invalid")
    if len(pcm) % 640:
        pcm += bytes(640 - len(pcm) % 640)
    return pcm


def run(device, pcm, cancel_on_playback=False, timeout=300, clock=time.monotonic, pause=time.sleep):
    before = device.start_control()
    if before.get("status") != "listening" or before.get("last_error") is not None:
        raise RuntimeError("device_not_idle")
    base = before["audio"]
    device.control({"action": "fixed-pcm-start"})
    try:
        for offset in range(0, len(pcm), 640):
            frame = base64.b64encode(pcm[offset:offset + 640]).decode("ascii")
            device.control({"action": "fixed-pcm-frame", "data": frame})
        device.control({"action": "fixed-pcm-end"})
        deadline = clock() + timeout
        cancelled = False
        cancel_proof = None
        while clock() < deadline:
            current = device.control({"action": "status"})
            audio = current.get("audio")
            if audio is None:
                if not cancelled:
                    raise RuntimeError("audio_runtime_unavailable")
                pause(.1)
                continue
            playing = audio["playback_first_write_ms"] > base.get("playback_first_write_ms", 0)
            if cancel_on_playback and playing and not cancelled:
                cancel_proof = device.control({"action": "fixed-pcm-cancel"})
                proof_audio = cancel_proof.get("audio")
                if (proof_audio is None
                        or proof_audio["playback_first_write_ms"] <= base.get("playback_first_write_ms", 0)
                        or proof_audio["playback_released_ms"] < proof_audio["playback_first_write_ms"]):
                    raise RuntimeError("fixed_pcm_cancel_release_unproven")
                cancelled = True
            terminal = current["status"] in {"listening", "run_failed"}
            changed = audio["fixed_pcm_runs"] > base.get("fixed_pcm_runs", 0)
            if terminal and (changed or cancel_proof is not None):
                if cancel_proof is not None:
                    proof = dict(current)
                    proof["audio"] = cancel_proof["audio"]
                    proof["connection_recovered"] = current.get("connections", 0) > cancel_proof.get("connections", 0)
                    return before, proof, cancelled
                return before, current, cancelled
            pause(.1)
        raise RuntimeError("fixed_pcm_validation_timeout")
    except BaseException:
        try:
            device.control({"action": "fixed-pcm-cancel"})
        except Exception:
            pass
        raise


def safe_report(before, after, cancelled, source):
    old, new = before["audio"], after["audio"]
    first, drained = new["playback_first_write_ms"], new["playback_drained_ms"]
    return {
        "source": str(source), "household_audio": False, "status": after["status"],
        "last_error": after["last_error"], "cancelled": cancelled,
        "connection_recovered": after.get("connection_recovered", False),
        "delta": {key: new[key] - old.get(key, 0) for key in
                  ("commands", "stt_results", "tts_streams", "completed",
                   "fixed_pcm_runs", "fixed_pcm_cancels")},
        "playback": {"first_write_ms": first, "drained_ms": drained,
                     "duration_ms": drained - first if first and drained else None,
                     "released_ms": new["playback_released_ms"],
                     "buffer_high_water_bytes": new["playback_buffer_high_water_bytes"],
                     "underruns": new["playback_underruns"]},
        "text_saved": False, "credentials_saved": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial")
    parser.add_argument("wav", type=Path)
    parser.add_argument("--confirm-device", required=True, choices=["r1-sample01"])
    parser.add_argument("--cancel-on-playback", action="store_true")
    args = parser.parse_args()
    pcm = load_pcm(args.wav)
    device = admin.Device(args.serial)
    device.verify()
    before, after, cancelled = run(device, pcm, args.cancel_on_playback)
    print(json.dumps(safe_report(before, after, cancelled, args.wav), ensure_ascii=False))


if __name__ == "__main__":
    main()
