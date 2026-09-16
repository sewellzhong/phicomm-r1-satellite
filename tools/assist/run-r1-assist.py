#!/usr/bin/env python3
"""Trigger one real Home Assistant Assist Satellite TTS announcement.

This is the current NativeSatelliteService-era replacement for the removed
AssistRuntimeService bootstrap script.  It does not install, configure, or
store anything on the R1.  Home Assistant performs the TTS playback through
the satellite's supported announce path.  The operator can say Alexa while
that playback is active, which is the useful path for the current AEC
input/output check.  It deliberately does not call ask_question: the current
R1 does not advertise remote START_CONVERSATION capability.

The HA token is accepted only from --token-file or R1_HA_TOKEN.  It is never
printed, included in a report, or accepted as a command-line value.
"""

import argparse
import json
import os
from pathlib import Path
import re
import ssl
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_ENTITY = "assist_satellite.r1_yuan_sheng_yu_yin_assist_satellite"
ENTITY_RE = re.compile(r"assist_satellite\.[a-z0-9_]+\Z")


class AssistTriggerError(RuntimeError):
    """A deliberately non-secret diagnostic."""


def read_token(token_file: Path | None, token_env: str) -> str:
    if token_file is not None and token_env in os.environ:
        raise AssistTriggerError("choose_token_file_or_token_env")
    if token_file is not None:
        try:
            info = token_file.lstat()
        except OSError as error:
            raise AssistTriggerError("token_file_unreadable") from error
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise AssistTriggerError("token_file_must_be_regular")
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise AssistTriggerError("token_file_must_be_owner_0600")
        try:
            token = token_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise AssistTriggerError("token_file_unreadable") from error
        if not token.endswith("\n"):
            raise AssistTriggerError("token_file_must_contain_one_line")
        token = token.rstrip("\r\n")
    else:
        token = os.environ.get(token_env, "")
    if not token or token != token.strip() or "\n" in token or "\r" in token:
        raise AssistTriggerError("ha_token_required")
    return token


class HomeAssistant:
    def __init__(self, base_url: str, token: str, timeout: float):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query
                or parsed.fragment):
            raise AssistTriggerError("invalid_ha_url")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, data=None):
        body = None if data is None else json.dumps(
            data, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            context = ssl.create_default_context() if self.base_url.startswith("https://") else None
            with urllib.request.urlopen(request, timeout=self.timeout, context=context) as response:
                payload = response.read(1024 * 1024)
                status = response.status
        except urllib.error.HTTPError as error:
            # The status code is useful for diagnosis and contains no token or
            # response body.  Never print the server's error text here.
            raise AssistTriggerError("ha_http_" + str(error.code)) from error
        except urllib.error.URLError as error:
            reason = error.reason
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise AssistTriggerError("ha_tls_certificate_failed") from error
            raise AssistTriggerError("ha_network_unreachable") from error
        except (TimeoutError, OSError) as error:
            raise AssistTriggerError("ha_network_unreachable") from error
        if status < 200 or status >= 300:
            raise AssistTriggerError("ha_request_failed")
        if not payload:
            return None
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AssistTriggerError("ha_response_invalid") from error

    def announce(self, entity_id: str, message: str):
        # preannounce=false avoids an additional cue audio segment in the AEC
        # experiment; the message itself is rendered by HA as TTS.
        return self.request("POST", "/api/services/assist_satellite/announce", {
            "entity_id": entity_id,
            "message": message,
            "preannounce": False,
        })

    def state(self, entity_id: str):
        encoded = urllib.parse.quote(entity_id, safe="")
        result = self.request("GET", "/api/states/" + encoded)
        if not isinstance(result, dict) or not isinstance(result.get("state"), str):
            raise AssistTriggerError("ha_state_response_invalid")
        return result["state"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ha-url", required=True,
                        help="HA origin, for example https://ha.example.local")
    parser.add_argument("--entity-id", default=DEFAULT_ENTITY)
    parser.add_argument("--question", required=True,
                        help="text to render through the satellite as TTS")
    token_group = parser.add_mutually_exclusive_group()
    token_group.add_argument("--token-file", type=Path,
                             help="owner-only 0600 file containing one token line")
    token_group.add_argument("--token-env", default="R1_HA_TOKEN",
                             help="environment variable containing the token")
    parser.add_argument("--wait-seconds", type=float, default=15.0,
                        help="poll satellite state after submission (default: 15)")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    if not ENTITY_RE.fullmatch(args.entity_id):
        parser.error("--entity-id must name an assist_satellite entity")
    if not args.question.strip() or len(args.question) > 512:
        parser.error("--question must contain 1-512 characters")
    if not 0 <= args.wait_seconds <= 300:
        parser.error("--wait-seconds must be between 0 and 300")
    if args.timeout <= 0 or args.timeout > 120:
        parser.error("--timeout must be between 0 and 120")

    token = read_token(args.token_file, args.token_env)
    try:
        ha = HomeAssistant(args.ha_url, token, args.timeout)
        ha.announce(args.entity_id, args.question)
        print("HA announce submitted; say Alexa while the R1 is playing TTS.", flush=True)

        deadline = time.monotonic() + args.wait_seconds
        previous = None
        while time.monotonic() < deadline:
            try:
                current = ha.state(args.entity_id)
            except AssistTriggerError:
                # The service has already been accepted.  Do not turn a
                # transient state read failure into a second HA invocation.
                break
            if current != previous:
                print("satellite_state=" + current, flush=True)
                previous = current
            time.sleep(0.5)
        return 0
    finally:
        token = ""


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        raise SystemExit(130)
    except AssistTriggerError as error:
        print("Assist trigger failed: " + str(error), file=sys.stderr)
        raise SystemExit(1)
