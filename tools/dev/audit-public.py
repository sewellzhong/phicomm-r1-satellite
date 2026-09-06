#!/usr/bin/env python3
"""Check Git's proposed public file set; print filenames/rules, never secret values."""
from pathlib import Path
import re
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[2]
PATTERNS = {
    'private-key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'github-token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b',
    'jwt': rb'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}',
    'credential-value': rb'(?i)["\x27]?(?:password|access_token|refresh_token|long_lived_token|noise_psk)["\x27]?\s*[:=]\s*["\x27][A-Za-z0-9+/=_-]{24,}["\x27]',
}
ALLOWED_EVIDENCE = {'test-results/README.md','test-results/public/index.json','test-results/public/structured.json'}

def main():
    files = subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=ROOT).decode().split('\0')
    errors=[]
    for name in sorted(set(files)-{''}):
        path=ROOT/name
        if not path.is_file():
            errors.append((name,'missing-file'));continue
        if path.is_symlink():errors.append((name,'symlink'))
        if name.startswith(('local-deps/','local-models/','local-secrets/')) or (name.startswith('test-results/') and name not in ALLOWED_EVIDENCE):
            errors.append((name,'private-path'))
        if path.suffix.lower() in {'.apk','.aar','.so','.tflite','.onnx','.wav','.pcm','.r1diag','.keystore','.jks','.pem','.key','.p12','.pfx'}:
            errors.append((name,'binary-or-private-material'))
        data=path.read_bytes()
        if len(data)>5*1024*1024:errors.append((name,'oversize'))
        for rule,pattern in PATTERNS.items():
            if re.search(pattern,data):errors.append((name,rule))
    for name,rule in errors:print(f'{rule}: {name}',file=sys.stderr)
    print(f'Public file scan: {len(set(files)-{""})} files, {len(errors)} findings. Review provenance and prose separately.')
    return bool(errors)
if __name__=='__main__':sys.exit(main())
