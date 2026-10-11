"""Read-only package integrity check; not a substitute for local runtime audit."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def verify(root=ROOT):
    receipt=json.loads((root/'references'/'validation.json').read_text())
    bad=[]
    for relative,expected in receipt['files'].items():
        path=root/relative
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:bad.append(relative)
    if bad:return {'verified':False,'changed_or_missing':bad}
    return {'verified':True,'version':receipt['version'],'files_checked':len(receipt['files']),
        'maintainer_tests':receipt['tests'],'maintainer_runtime_audit':receipt['runtime_audit'],
        'local_runtime_audit_required':True,'real_patient_enabled':False}

if __name__=='__main__':
    try:
        result=verify();print(json.dumps(result,indent=2));sys.exit(0 if result['verified'] else 1)
    except Exception:print('Package validation receipt missing or invalid',file=sys.stderr);sys.exit(1)
