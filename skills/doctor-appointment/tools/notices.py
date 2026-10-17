"""Start-up banner: clinic changes the patient has not been shown yet.

Run by start.sh before the Patient Assistant opens, so the patient sees moves,
cancellations and clinic bookings even if the chat model never mentions them.
Prints nothing when there is nothing new or the appointment book is unreachable.
"""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from core import ROOT

def configured_patient(folder=ROOT/'patient-agent'):
    args=json.loads((folder/'.mcp.json').read_text())['mcpServers']['clinic']['args']
    return args[args.index('--patient')+1] if '--patient' in args else 'patient-a'

def banner(patient,log=None):
    """Sentences for changes not told yet; the runtime records them as told."""
    from server import make_runtime
    runtime=make_runtime('patient',patient)
    if log is not None:runtime.service.notices_seen=log
    return runtime.call('get_my_appointments',{}).get('tell_patient_first',[])

if __name__=='__main__':
    from runtime_python import ensure_package_interpreter
    ensure_package_interpreter(ROOT)
    try:lines=banner(configured_patient())
    except Exception:lines=[]
    if lines:print('\n'.join(['','  Message from the clinic:',*('  - '+x for x in lines),'']))
