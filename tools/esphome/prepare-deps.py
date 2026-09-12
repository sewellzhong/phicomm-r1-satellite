#!/usr/bin/env python3
"""Fetch only pinned Native API build dependencies; no model/credential downloads."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'protocol/esphome/manifest.json'
LOCK = ROOT / 'tools/esphome/requirements-host.lock'
VENV = ROOT / 'local-deps/esphome-interop-venv'
LOCK_MARKER = VENV / '.requirements.sha256'
EXPECTED_PYTHON = (3, 12)
EXPECTED_PACKAGES = {
    'aioesphomeapi': '45.6.1',
    'aiohappyeyeballs': '2.7.1',
    'async-interrupt': '1.2.2',
    'cffi': '2.1.1',
    'chacha20poly1305-reuseable': '0.13.2',
    'cryptography': '50.0.1',
    'ifaddr': '0.2.0',
    'noiseprotocol': '0.3.1',
    'protobuf': '7.36.1',
    'pycparser': '3.0',
    'tzdata': '2026.3',
    'tzlocal': '5.4.4',
    'zeroconf': '0.151.3',
}


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def environment_is_valid(lock_digest):
    python = VENV / 'bin/python'
    if not python.is_file() or not LOCK_MARKER.is_file():
        return False
    if LOCK_MARKER.read_text().strip() != lock_digest:
        return False
    probe = (
        'import importlib.metadata, json, sys; '
        'expected=json.loads(sys.argv[1]); '
        'actual={name: importlib.metadata.version(name) for name in expected}; '
        'assert sys.version_info[:2] == (3, 12), sys.version; '
        'assert actual == expected, (actual, expected); '
        'import aioesphomeapi, google.protobuf, noise.connection'
    )
    result = subprocess.run(
        [str(python), '-c', probe, json.dumps(EXPECTED_PACKAGES, sort_keys=True)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def prepare_python_environment():
    if sys.version_info[:2] != EXPECTED_PYTHON:
        raise SystemExit('Supported host Python: 3.12')
    lock_digest = hashlib.sha256(LOCK.read_bytes()).hexdigest()
    if environment_is_valid(lock_digest):
        return
    if VENV.exists():
        shutil.rmtree(VENV)
    run(sys.executable, '-m', 'venv', str(VENV))
    python = VENV / 'bin/python'
    run(
        str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
        '--only-binary=:all:', '--require-hashes', '-r', str(LOCK),
    )
    LOCK_MARKER.write_text(lock_digest + '\n')
    if not environment_is_valid(lock_digest):
        raise SystemExit('Pinned host Python dependency verification failed')


def main():
    manifest = json.loads(MANIFEST.read_text())
    protoc = ROOT / 'local-deps/protoc-3.25.5/protoc'
    if not protoc.exists():
        data = urllib.request.urlopen(
            'https://repo.maven.apache.org/maven2/com/google/protobuf/'
            'protoc/3.25.5/protoc-3.25.5-linux-x86_64.exe', timeout=60
        ).read()
        if hashlib.sha256(data).hexdigest() != manifest['protoc']['sha256']:
            raise SystemExit('protoc checksum mismatch')
        protoc.parent.mkdir(parents=True, exist_ok=True)
        protoc.write_bytes(data)
        protoc.chmod(0o755)
    if hashlib.sha256(protoc.read_bytes()).hexdigest() != manifest['protoc']['sha256']:
        raise SystemExit('protoc checksum mismatch')

    source = ROOT / 'local-deps/src/noise-c'
    if not source.exists():
        source.mkdir(parents=True)
        run('git', 'init', str(source))
        run('git', '-C', str(source), 'remote', 'add', 'origin',
            'https://github.com/esphome/noise-c.git')
        run('git', '-C', str(source), 'fetch', '--depth', '1', 'origin',
            manifest['noise_c']['commit'])
        run('git', '-C', str(source), 'checkout', '--detach', 'FETCH_HEAD')
    actual_commit = subprocess.check_output(
        ['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True
    ).strip()
    if actual_commit != manifest['noise_c']['commit']:
        raise SystemExit('noise-c commit mismatch')

    prepare_python_environment()
    print('Pinned Native API build and Python dependencies verified.')


if __name__ == '__main__':
    main()
