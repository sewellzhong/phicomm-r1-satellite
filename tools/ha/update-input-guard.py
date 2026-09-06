#!/usr/bin/env python3
"""Compare-and-update component code only, with an on-host rollback copy. No config edits."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
from datetime import datetime,timezone
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'integrations/home_assistant/custom_components/r1_input_guard'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='home-assistant')
    parser.add_argument('--expected-hashes',type=Path,required=True)
    args=parser.parse_args()
    expected=json.loads(args.expected_hashes.read_text())
    for name,digest in expected.items():
        if not re.fullmatch(r'[A-Za-z0-9_./-]+',name) or '..' in name.split('/') or not re.fullmatch('[a-f0-9]{64}',digest):
            raise ValueError('invalid_expected_manifest')
    backup='/config/r1_component_backups/'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w') as archive:
        sums=[]
        for path in sorted(SOURCE.rglob('*')):
            if not path.is_file() or path.suffix not in ('.py','.json'):continue
            name='r1_input_guard/'+path.relative_to(SOURCE).as_posix()
            archive.add(path,arcname=name);sums.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+name)
        for name,data in [('SHA256SUMS','\n'.join(sums)+'\n'),
                          ('EXPECTED','\n'.join(d+'  '+n for n,d in sorted(expected.items()))+'\n'),
                          ('NAMES','\n'.join(sorted(expected))+'\n')]:
            raw=data.encode();info=tarfile.TarInfo(name);info.size=len(raw);archive.addfile(info,io.BytesIO(raw))
    script='''set -eu
base=/config/custom_components
target="$base/r1_input_guard"
backup=BACKUP_PATH
test -d "$target"
stage=$(mktemp -d "$base/.r1-native-stage-XXXXXXXX")
cleanup() {
  if test ! -d "$target" && test -d "$backup/r1_input_guard"; then mv "$backup/r1_input_guard" "$target"; fi
  rm -rf "$stage"
}
trap cleanup EXIT
tar -xf - -C "$stage"
(cd "$stage" && sha256sum -c SHA256SUMS)
(cd "$target" && sha256sum -c "$stage/EXPECTED")
(cd "$target" && find . -type f \\( -name '*.py' -o -name '*.json' \\) | sed 's|^./||' | sort) > "$stage/ACTUAL_NAMES"
cmp "$stage/NAMES" "$stage/ACTUAL_NAMES"
mkdir -p "$backup"
mv "$target" "$backup/r1_input_guard"
mv "$stage/r1_input_guard" "$target"
if ! ha core check; then
  mv "$target" "$stage/rejected"
  mv "$backup/r1_input_guard" "$target"
  echo R1_NATIVE_UPDATE_ROLLED_BACK >&2
  exit 1
fi
printf 'R1_NATIVE_CODE_UPDATED backup=%s\n' "$backup"
'''.replace('BACKUP_PATH',backup)
    subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',args.host,script],input=buffer.getvalue(),check=True)

if __name__=='__main__':main()
