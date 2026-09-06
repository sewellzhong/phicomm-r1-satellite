#!/usr/bin/env python3
"""Prepare pinned Linux x86_64 host-build dependencies; never contact a device."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import struct
import tarfile
import subprocess
import urllib.request
import wave

ROOT = Path(__file__).resolve().parents[2]
AARS = {
    'tensorflow-lite-api': '76f22dc18991211f7ad727c6862c832a9876057476fa458080a1a2280b4177d7',
    'tensorflow-lite': 'fc945337cff72a261e15013170968a8f321ef30ea7ec50e9043c683e4a719e00',
}

def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)

def main():
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise SystemExit('Supported host: Linux x86_64')
    for tool in ('java', 'git', 'cmake', 'make', 'cc', 'c++', 'sha256sum', 'rg'):
        if not shutil.which(tool):
            raise SystemExit(f'Missing required command: {tool}')
    sdk = Path(os.environ.get('ANDROID_SDK_ROOT', '/missing-sdk'))
    for item in ('ndk/27.0.12077973', 'platforms/android-35', 'build-tools/34.0.0'):
        if not (sdk / item).is_dir():
            raise SystemExit(f'Missing Android SDK component: {item}; set ANDROID_SDK_ROOT and install it with sdkmanager')
    deps = ROOT / 'local-deps'
    deps.mkdir(exist_ok=True)
    scanner = deps / 'gitleaks/gitleaks'
    archive = deps / 'gitleaks-8.30.1.tar.gz'
    expected = '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb'
    if not archive.exists():
        url = 'https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz'
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = response.read()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise SystemExit('Gitleaks checksum mismatch')
        archive.write_bytes(payload)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise SystemExit('Gitleaks checksum mismatch')
    scanner.parent.mkdir(exist_ok=True)
    with tarfile.open(archive) as bundle:
        scanner.write_bytes(bundle.extractfile('gitleaks').read())
    scanner.chmod(0o755)
    for name, expected in AARS.items():
        dest = deps / f'{name}-2.10.0.aar'
        if not dest.exists():
            url = f'https://repo.maven.apache.org/maven2/org/tensorflow/{name}/2.10.0/{dest.name}'
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != expected:
                raise SystemExit(f'Checksum mismatch: {name}')
            dest.write_bytes(data)
        if hashlib.sha256(dest.read_bytes()).hexdigest() != expected:
            raise SystemExit(f'Checksum mismatch: {name}')
    run('python3', 'tools/esphome/prepare-deps.py')
    run('python3', 'tools/kws/prepare-alexa-microwakeword.py')
    for name in ('microfrontend', 'vad', 'noise'):
        run('bash', f'tools/build-r1-{name}.sh')
    # Original synthetic development fixture, not licensed third-party speech.
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b''.join(struct.pack('<h', int(1000 * math.sin(2 * math.pi * 440 * i / 16000))) for i in range(1600)))
    for name in json.loads((ROOT / 'tools/dev/prompt-layout.json').read_text()):
        dest = deps / 'host-prompts/assets' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(audio.getvalue())
    (deps / 'host-prompts/assets/HOST_CHECK_ONLY').write_text('Synthetic tones; not for device deployment.\n')
    print('Host dependencies verified; host prompts are test tones, not Chinese speech.')

if __name__ == '__main__':
    main()
