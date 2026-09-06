#!/usr/bin/env python3
"""Fetch only pinned Native API build dependencies; no model/credential downloads."""
import hashlib,json,subprocess,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
m=json.loads((ROOT/'protocol/esphome/manifest.json').read_text())
p=ROOT/'local-deps/protoc-3.25.5/protoc'
if not p.exists():
    data=urllib.request.urlopen('https://repo.maven.apache.org/maven2/com/google/protobuf/protoc/3.25.5/protoc-3.25.5-linux-x86_64.exe').read()
    assert hashlib.sha256(data).hexdigest()==m['protoc']['sha256']
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(0o755)
assert hashlib.sha256(p.read_bytes()).hexdigest()==m['protoc']['sha256']
s=ROOT/'local-deps/src/noise-c'
if not s.exists():
    s.mkdir(parents=True)
    subprocess.run(['git','init',str(s)],check=True)
    subprocess.run(['git','-C',str(s),'remote','add','origin','https://github.com/esphome/noise-c.git'],check=True)
    subprocess.run(['git','-C',str(s),'fetch','--depth','1','origin',m['noise_c']['commit']],check=True)
    subprocess.run(['git','-C',str(s),'checkout','--detach','FETCH_HEAD'],check=True)
assert subprocess.check_output(['git','-C',str(s),'rev-parse','HEAD'],text=True).strip()==m['noise_c']['commit']
print('Pinned Native API build dependencies verified.')
