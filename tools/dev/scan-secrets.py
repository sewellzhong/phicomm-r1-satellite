#!/usr/bin/env python3
"""Scan only the proposed public worktree, never ignored private local files."""
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[2]

def main():
    scanner = ROOT / 'local-deps/gitleaks/gitleaks'
    if not scanner.is_file():
        raise SystemExit('Missing pinned Gitleaks; run python3 tools/dev/prepare.py')
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).decode().split('\0')
    with tempfile.TemporaryDirectory(prefix='r1-public-scan-') as directory:
        target = Path(directory)
        for name in sorted(set(names) - {''}):
            source = ROOT / name
            if source.is_symlink() or not source.is_file():
                raise SystemExit(f'Invalid public file: {name}')
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
        subprocess.run([str(scanner), 'dir', str(target), '--config', str(ROOT / '.gitleaks.toml'), '--redact', '--no-banner'], check=True)

if __name__ == '__main__':
    main()
