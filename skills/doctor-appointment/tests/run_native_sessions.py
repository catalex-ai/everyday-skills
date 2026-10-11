"""Opt-in real native Codex multi-turn E2E; not an offline unittest."""
import json,queue,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from core import ROOT,atomic
from server import PracticeRuntime
from audit import RPC

def turn(rpc,thread,prompt):
    rpc.call('turn/start',{'threadId':thread,'input':[{'type':'text','text':prompt}]})
    calls=[];messages=[];deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        try:event=rpc.messages.get(timeout=max(.01,deadline-time.monotonic()))
        except queue.Empty:break
        if event is None:raise RuntimeError('Native session terminated')
        method=event.get('method');params=event.get('params',{})
        if method=='item/completed':
            item=params.get('item',{})
            if item.get('type')=='mcpToolCall':calls.append(item)
            elif item.get('type')=='agentMessage':messages.append(item.get('text',''))
        if method=='turn/completed':return {'calls':calls,'messages':messages,'status':params.get('turn',{}).get('status')}
    raise TimeoutError('Native conversation turn timed out')

def conversation(role,day,hour,patient_ref=None):
    rpc=RPC(role)
    try:
        rpc.call('initialize',{'clientInfo':{'name':'doctor-appointment-e2e','version':'0.2.0'},'capabilities':{'experimentalApi':True}})
        rpc.process.stdin.write('{"method":"initialized"}\n');rpc.process.stdin.flush()
        thread=rpc.call('thread/start',{'cwd':str(ROOT/(role+'-agent')),'ephemeral':True})['thread']['id']
        target='for me' if role=='patient' else 'for configured patient-b'
        request='native-patient-e2e' if role=='patient' else 'native-doctor-e2e'
        first=turn(rpc,thread,f'Book a SYNTHETIC practice appointment {target} on {day} at {hour}:00 +05:30, using request_id {request}. Use only clinic tools. Show the proposed appointment before asking for confirmation. No Google access.')
        second=turn(rpc,thread,f'Yes, I explicitly confirm booking that exact synthetic appointment {target} on {day} at {hour}:00 +05:30. Keep the same request ID and submit its action-bound confirmation token. Then '+('show my appointments.' if role=='patient' else f'show the clinic schedule for {day}.'))
        results=[first,second]
        if not confirmed({'turns':results},'book_my_appointment' if role=='patient' else 'doctor_book_appointment'):
            results.append(turn(rpc,thread,f'Yes, I confirm the returned proposal for {day} at {hour}:00 +05:30 {target}. Submit its confirmation token with the same request ID now. Then '+('show my appointments.' if role=='patient' else f'show the schedule for {day}.')))
        return {'turns':results}
    finally:rpc.close()

def confirmed(result,tool):
    for turn_result in result['turns']:
        for call in turn_result['calls']:
            if call.get('tool')!=tool:continue
            for block in (call.get('result') or {}).get('content',[]):
                try:
                    if json.loads(block.get('text','{}')).get('calendar_confirmed'):return True
                except ValueError:pass
    return False

def main():
    runtime=PracticeRuntime('patient');mine=runtime.call('get_my_appointments',{})
    day=mine['appointments'][0]['start'][:10]
    patient=conversation('patient',day,14)
    doctor=conversation('doctor',day,16,'patient-b')
    a=runtime.call('get_my_appointments',{})['appointments'];b=PracticeRuntime('patient','patient-b').call('get_my_appointments',{})['appointments']
    report={'patient':patient,'doctor':doctor,'patient_booking_verified':any(e['start']==day+'T14:00:00+05:30' and e['status']=='confirmed' for e in a) and confirmed(patient,'book_my_appointment'),
       'doctor_booking_verified':any(e['start']==day+'T16:00:00+05:30' and e['status']=='confirmed' for e in b) and confirmed(doctor,'doctor_book_appointment'),
       'patient_isolation_verified':not {e['id'] for e in a}&{e['id'] for e in b},'google_accessed':False}
    report['passed']=all(report[k] for k in ('patient_booking_verified','doctor_booking_verified','patient_isolation_verified'))
    atomic(ROOT/'config'/'native-e2e-report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('patient','doctor')},indent=2))
    sys.exit(0 if report['passed'] else 1)

if __name__=='__main__':main()
