#!/usr/bin/env python3
"""Stage a private one-shot HA commissioning request via authorized config-admin SSH.

The HA component consumes the request at startup and uses regular HA config APIs.
No SSH forwarding, Core token extraction, or direct .storage writes.
"""
import argparse
import json
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--host", default="home-assistant")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--upgrade-interaction", metavar="MAC")
    parser.add_argument("--verify-interaction", metavar="MAC")
    args = parser.parse_args()
    if args.verify_interaction: request = {"action": "verify_interaction", "protocol_mac": args.verify_interaction}
    elif args.upgrade_interaction: request = {"action": "upgrade_interaction", "protocol_mac": args.upgrade_interaction}
    elif args.inspect: request = {"action": "inspect"}
    else:
        if sys.stdin.isatty(): raise RuntimeError("private_pairing_pipe_required")
        supplied = json.loads(sys.stdin.read(8192))
        request = {key: supplied[key] for key in ("host", "protocol_mac", "name", "noise_psk")}
        request["action"] = "pair"; supplied.clear()
    script = '''set -eu
umask 077
test -f /config/custom_components/r1_input_guard/commissioning.py
test ! -e /config/.r1_native_commission.json
stage=$(mktemp /config/.r1-native-request-XXXXXXXX)
trap 'rm -f "$stage"' EXIT
cat > "$stage"
chmod 600 "$stage"
rm -f /config/.r1_native_commission_result.json
mv "$stage" /config/.r1_native_commission.json
if ! ha core check; then
  rm -f /config/.r1_native_commission.json
  exit 1
fi
ha core restart
'''
    subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.host, script],
                   input=json.dumps(request), text=True, check=True, stdout=subprocess.DEVNULL, timeout=120)
    request.clear()
    deadline = time.monotonic() + 210
    while time.monotonic() < deadline:
        response = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", args.host,
                                   "cat /config/.r1_native_commission_result.json"], capture_output=True, text=True, timeout=15)
        if response.returncode == 0:
            report = json.loads(response.stdout)
            print(json.dumps(report, ensure_ascii=False))
            if not report.get("ok"): raise RuntimeError("ha_commissioning_failed")
            return
        time.sleep(2)
    raise RuntimeError("ha_commissioning_result_timeout")

if __name__ == "__main__":
    try: main()
    except Exception as error:
        print("HA native setup failed: " + type(error).__name__, file=sys.stderr)
        sys.exit(1)
