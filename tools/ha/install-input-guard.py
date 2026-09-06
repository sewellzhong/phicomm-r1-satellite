#!/usr/bin/env python3
"""First install only. Stage/hash-check an independent HA integration; never overwrite."""
import argparse
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'integrations/home_assistant/custom_components/r1_input_guard'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='home-assistant')
    args=parser.parse_args()
    files=sorted(p for p in SOURCE.rglob('*') if p.is_file() and p.suffix in ('.py','.json'))
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w') as archive:
        sums=[]
        for path in files:
            name='r1_input_guard/'+path.relative_to(SOURCE).as_posix()
            archive.add(path,arcname=name)
            sums.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+name)
        data=('\n'.join(sums)+'\n').encode()
        info=tarfile.TarInfo('SHA256SUMS');info.size=len(data)
        archive.addfile(info,io.BytesIO(data))
    script='''set -eu
base=/config/custom_components
test ! -e "$base/r1_input_guard" || { echo 'Refusing to overwrite existing integration' >&2; exit 64; }
stage=$(mktemp -d "$base/.r1-guard-stage-XXXXXXXX")
trap 'rm -rf "$stage"' EXIT
tar -xf - -C "$stage"
cd "$stage"
sha256sum -c SHA256SUMS
test ! -e "$base/r1_input_guard"
mv "$stage/r1_input_guard" "$base/r1_input_guard"
echo R1_INPUT_GUARD_FILES_INSTALLED
'''
    subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',args.host,script],
                   input=buffer.getvalue(),check=True)

if __name__=='__main__':main()
