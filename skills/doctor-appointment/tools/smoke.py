"""Fast, offline consumer compatibility check; no full regression suite."""
import json,sys,tempfile
from pathlib import Path
from core import Denied
from server import PracticeRuntime

def smoke():
    if sys.version_info<(3,11):raise RuntimeError('Python 3.11+ required')
    with tempfile.TemporaryDirectory(prefix='doctor-practice-') as tmp:
        state=Path(tmp)/'practice.json'
        a=PracticeRuntime('patient','patient-a',state);b=PracticeRuntime('patient','patient-b',state);doctor=PracticeRuntime('doctor',state_path=state)
        own_a={e['id'] for e in a.call('get_my_appointments',{})['appointments']}
        own_b={e['id'] for e in b.call('get_my_appointments',{})['appointments']}
        if own_a!={'a-demo','cancelled-demo'} or own_b!={'b-demo'}:raise RuntimeError('Isolation smoke check failed')
        try:a.call('cancel_my_appointment',{'appointment_id':'b-demo'})
        except Denied:pass
        else:raise RuntimeError('Ownership enforcement failed')
        verification=doctor.call('doctor_verify_synthetic_appointment',{})
        if not all(verification[k] for k in ('calendar_write_verified','sync_failure_recovered','no_duplicate_rows','patient_isolation','cancellation_synced')):raise RuntimeError('Verification failed')
        return {'passed':True,'patient_a_records':len(own_a),'patient_b_records':len(own_b),'doctor_verification':verification,'google_accessed':False}

if __name__=='__main__':print(json.dumps(smoke(),indent=2))
