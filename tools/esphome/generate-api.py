#!/usr/bin/env python3
"""Generate Java Lite and message IDs from the verified, pinned ESPHome schema."""
import hashlib,json,re,subprocess,tempfile,urllib.request,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PROTO=ROOT/'protocol/esphome'
OUT=ROOT/'android/r1-probe/app/build/generated/esphome'
PROTOC=ROOT/'local-deps/protoc-3.25.5/protoc'

def main():
    manifest=json.loads((PROTO/'manifest.json').read_text())
    for name,expected in manifest['files'].items():
        assert hashlib.sha256((PROTO/name).read_bytes()).hexdigest()==expected,name
    assert hashlib.sha256(PROTOC.read_bytes()).hexdigest()=='d69b0a9ac8264bb3d464ae22742430943aa0a6cdf3734180af5a607c0bf8adaa'
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp)
        for name,outer in [('api.proto','EsphomeApi'),('api_options.proto','EsphomeOptions')]:
            s=re.sub(r"\bvoid\b", "RpcVoid", (PROTO/name).read_text()) # Java reserved word; empty RPC type only.
            pos=s.index(';')+1
            s=s[:pos]+f'\noption java_package = "dev.sewellzhong.r1probe.esphome.proto";\noption java_outer_classname = "{outer}";\n'+s[pos:]
            (p/name).write_text(s)
        desc=p/'google/protobuf/descriptor.proto';desc.parent.mkdir(parents=True)
        desc.write_bytes((PROTO/'descriptor.proto').read_bytes())
        subprocess.run([str(PROTOC),'-I'+str(p),'--java_out=lite:'+str(OUT),str(p/'api.proto')],check=True)
    source=re.sub(r'//[^\n]*','',(PROTO/'api.proto').read_text())
    pairs=[]
    for name,body in re.findall(r'message\s+(\w+)\s*\{([^}]*)',source):
        match=re.search(r'option\s*\(id\)\s*=\s*(\d+)\s*;',body)
        if match:pairs.append((name,match[1]))
    assert len(pairs)==len(re.findall(r'option\s*\(id\)',source)) and len({n for _,n in pairs})==len(pairs)
    target=OUT/'dev/sewellzhong/r1probe/esphome/proto/MessageIds.java'
    target.write_text('// Generated from pinned api.proto. Do not edit.\npackage dev.sewellzhong.r1probe.esphome.proto;\npublic final class MessageIds {\n'+''.join('    public static final int '+name+' = '+n+';\n' for name,n in pairs)+'    private MessageIds() {}\n}\n')
    print('Generated',len(pairs),'message IDs and Java Lite schema.')
if __name__=='__main__':main()
