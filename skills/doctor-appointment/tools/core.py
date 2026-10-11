"""Trusted scheduling and authorization. No model-selected identity or adapters."""
from __future__ import annotations
import copy, hashlib, json, os, re, secrets
from datetime import datetime, timedelta, time, date
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from pathlib import Path
from contextlib import contextmanager
import fcntl

ROOT = Path(__file__).resolve().parents[1]
class Denied(Exception): pass
class Conflict(Exception): pass
class Uncertain(Exception): pass

def stamp(value):
    d = datetime.fromisoformat(value)
    if d.tzinfo is None or d.utcoffset() is None: raise ValueError('Timezone offset required')
    return d

def atomic(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        os.chmod(tmp, 0o600); json.dump(obj, f, indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

@contextmanager
def lock(path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path, 'a') as f:
        os.chmod(path, 0o600); fcntl.flock(f, fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(f, fcntl.LOCK_UN)

@dataclass(frozen=True)
class Identity:
    subject: str
    role: str
    clinic: str
    source: str
    verified: bool

PATIENT = {'get_available_slots','get_my_appointments','book_my_appointment',
           'cancel_my_appointment','reschedule_my_appointment','get_clinic_information'}
DOCTOR = {'doctor_get_schedule','doctor_get_appointment','doctor_configure_clinic',
          'doctor_block_time','doctor_unblock_time','doctor_cancel_appointment',
          'doctor_reschedule_appointment','doctor_sync_register','doctor_sync_status',
          'doctor_review_issues','doctor_open_spreadsheet','doctor_connection_status','doctor_verify_synthetic_appointment','doctor_book_appointment'}

DEFAULT = dict(clinic_id='synthetic-clinic', clinic_name='Practice Clinic', timezone='Asia/Kolkata',
    working_days=[0,1,2,3,4,5], opening='09:00', closing='17:00', breaks=[['13:00','14:00']],
    duration_minutes=30, buffer_minutes=10, address='Synthetic address', contact='Synthetic contact',
    calendar_id='', spreadsheet_id='', confirmation_policy='Confirm the selected slot before booking.',
    cancellation_policy='Confirm cancellation before submitting.')

def validate_config(c):
    if set(c) != set(DEFAULT): raise ValueError('Unknown or missing configuration fields')
    ZoneInfo(c['timezone'])
    for k in ('duration_minutes','buffer_minutes'):
        if type(c[k]) is not int or not 0 <= c[k] <= 240: raise ValueError('Invalid duration/buffer')
    if c['duration_minutes'] < 5: raise ValueError('Minimum duration is 5 minutes')
    if not c['working_days'] or any(type(x) is not int or x not in range(7) for x in c['working_days']): raise ValueError('Invalid working days')
    if time.fromisoformat(c['opening']) >= time.fromisoformat(c['closing']): raise ValueError('Invalid hours')
    for a,b in c['breaks']:
        if not time.fromisoformat(c['opening']) <= time.fromisoformat(a) < time.fromisoformat(b) <= time.fromisoformat(c['closing']): raise ValueError('Invalid break')
    for k,v in c.items():
        if k not in ('working_days','breaks','duration_minutes','buffer_minutes'):
            if not isinstance(v,str) or len(v)>500: raise ValueError('Invalid configuration text')
    if c['calendar_id']=='primary': raise ValueError('Select an explicit clinic calendar ID')
    if c['spreadsheet_id'] and not re.fullmatch(r'[A-Za-z0-9_-]{10,200}',c['spreadsheet_id']): raise ValueError('Invalid spreadsheet ID')
    return c

def public_event(e):
    # No raw event summary/description/contact data reaches an agent.
    return {k:copy.deepcopy(e[k]) for k in ('id','start','end','status','kind') if k in e}

def doctor_event(e):
    result=public_event(e)
    if e.get("kind")=="appointment" and e.get("owner"):
        result["patient_reference"]=e["owner"]
    return result

class Service:
    def __init__(self, identity, calendar, sheets, config=None, config_path=None):
        self.identity, self.cal, self.sheets = identity, calendar, sheets
        self.config = validate_config(copy.deepcopy(config or DEFAULT))
        self.config_path = config_path
        self.pending = {}
    def authorize(self, tool):
        i = self.identity
        if not i.verified or i.clinic != self.config['clinic_id'] or i.source not in ('synthetic','gateway'): raise Denied('Verified identity required')
        if tool not in (PATIENT if i.role=='patient' else DOCTOR if i.role=='doctor' else set()): raise Denied('Operation not authorized')
    def owned(self, ident):
        e=self.cal.get(ident)
        if not e or e.get('clinic')!=self.identity.clinic or e.get('owner')!=self.identity.subject: raise Denied('Appointment unavailable')
        return e
    def managed(self, ident, kind='appointment'):
        e=self.cal.get(ident)
        if not e or e.get('clinic')!=self.identity.clinic or e.get('kind')!=kind: raise Denied('Managed event unavailable')
        return e
    def confirm(self, action, payload, token=None):
        digest=hashlib.sha256(json.dumps([action,payload],sort_keys=True).encode()).hexdigest()
        if token is None:
            t=secrets.token_urlsafe(24); self.pending[t]=(digest,datetime.now().timestamp()+300)
            return {'confirmation_required':True,'confirmation_token':t,'action':action,'details':payload}
        entry=self.pending.pop(token,None)
        if not entry or entry[0]!=digest or entry[1]<datetime.now().timestamp(): raise Denied('Fresh action-specific confirmation required')
        return None
    def interval(self, start):
        a=stamp(start).astimezone(ZoneInfo(self.config['timezone']))
        b=a+timedelta(minutes=self.config['duration_minutes'])
        if a < datetime.now(a.tzinfo): raise ValueError('Past appointment')
        return a,b
    def valid_hours(self,a,b):
        c=self.config
        if a.date()!=b.date() or a.weekday() not in c['working_days']: return False
        if not time.fromisoformat(c['opening'])<=a.time().replace(tzinfo=None)<b.time().replace(tzinfo=None)<=time.fromisoformat(c['closing']): return False
        return not any(a.time().replace(tzinfo=None)<time.fromisoformat(y) and b.time().replace(tzinfo=None)>time.fromisoformat(x) for x,y in c['breaks'])
    def conflicts(self,a,b,exclude=None):
        pad=timedelta(minutes=self.config['buffer_minutes'])
        # Busy intervals only; patient paths never list raw Calendar events.
        return self.cal.busy(a-pad,b+pad,exclude)
    def available(self,a,b,exclude=None):
        return self.valid_hours(a,b) and not self.conflicts(a,b,exclude)
    def slots(self, day, preferred_start=None):
        d=date.fromisoformat(day); z=ZoneInfo(self.config['timezone']); c=self.config
        a=datetime.combine(d,time.fromisoformat(c['opening']),z)
        finish=datetime.combine(d,time.fromisoformat(c['closing']),z)
        slots=[]
        while a+timedelta(minutes=c['duration_minutes'])<=finish:
            b=a+timedelta(minutes=c['duration_minutes'])
            if a>datetime.now(z) and self.available(a,b): slots.append(a.isoformat())
            a+=timedelta(minutes=c['duration_minutes']+c['buffer_minutes'])
        if preferred_start:
            preferred=stamp(preferred_start).astimezone(z)
            if preferred.date()!=d:raise ValueError('Requested start must match day in clinic timezone')
            finish=preferred+timedelta(minutes=c['duration_minutes'])
            if preferred>datetime.now(z) and self.available(preferred,finish) and preferred.isoformat() not in slots:slots.append(preferred.isoformat())
        return {'slots':sorted(slots),'timezone':c['timezone']}
    def book(self,start,request_id,confirmation_token=None):
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',request_id): raise ValueError('Request ID must contain 8–100 safe characters')
        a,b=self.interval(start)
        ident=hashlib.sha256(f'{self.identity.clinic}:{self.identity.subject}:{request_id}'.encode()).hexdigest()
        existing=self.cal.get(ident)
        if existing:
            if existing.get('owner')!=self.identity.subject or existing.get('start')!=a.isoformat(): raise Conflict('Request ID reused for different appointment')
            return {'calendar_confirmed':True,'appointment':public_event(existing)}
        if not self.available(a,b): return {'conflict':True,'alternatives':self.slots(a.date().isoformat())}
        draft={'id':ident,'start':a.isoformat(),'end':b.isoformat(),'status':'confirmed','kind':'appointment','owner':self.identity.subject,'clinic':self.identity.clinic}
        needed=self.confirm('book',draft,confirmation_token)
        if needed:return needed
        # Recheck immediately before the write; local lock cannot prevent external writers.
        if not self.available(a,b): return {'conflict':True,'alternatives':self.slots(a.date().isoformat())}
        try:self.cal.insert(draft)
        except (TimeoutError,Uncertain):
            found=self.cal.get(ident)
            if not found or any(found.get(k)!=v for k,v in draft.items()): raise Uncertain('Write unresolved; retry SAME request ID. Do not confirm booking.')
        found=self.cal.get(ident)
        if not found or any(found.get(k)!=v for k,v in draft.items()): raise Uncertain('Calendar verification failed')
        overlap=self.conflicts(a,b,ident)
        return {'calendar_confirmed':True,'appointment':public_event(found),'external_conflict_detected':bool(overlap),'sheets_status':'pending'}
    def change(self,action,ident,start=None,token=None,doctor=False):
        e=self.managed(ident) if doctor else self.owned(ident)
        if action=='cancel' and e['status']=='cancelled':return {'calendar_confirmed':True,'appointment':public_event(e)}
        if action=='reschedule' and e['status']=='cancelled':raise Denied('Cancelled appointments cannot be rescheduled')
        payload={'appointment_id':ident,'version':e.get('etag',json.dumps(e,sort_keys=True))}
        if start:
            a,b=self.interval(start);payload['start']=a.isoformat()
            if not self.available(a,b,ident):return {'conflict':True,'alternatives':self.slots(a.date().isoformat())}
        needed=self.confirm(action,payload,token)
        if needed:return needed
        updated=copy.deepcopy(e)
        if action=='cancel':updated['status']='cancelled'
        else:updated.update(start=a.isoformat(),end=b.isoformat())
        try:self.cal.update(updated,e.get('etag'))
        except (TimeoutError,Uncertain):pass
        found=self.cal.get(ident)
        if not found or any(found.get(k)!=updated.get(k) for k in ('start','end','status')): raise Uncertain('Change unverified; retry after reviewing Calendar')
        return {'calendar_confirmed':True,'appointment':public_event(found)}
    def sync(self):
        # Register is reporting state, never read by scheduling operations.
        records=self.sheets.read_records(); seen=set()
        for e in self.cal.managed_events(self.identity.clinic):
            if e.get('kind')!='appointment':continue
            seen.add(e['id']); records[e['id']]=records.get(e['id'],{})|public_event(e)|{'last_seen':datetime.now().isoformat(),'issue':''}
        for ident,row in records.items():
            if ident not in seen and row.get('status')!='cancelled': row['issue']='missing_from_calendar_review_required'
        try:self.sheets.write_records(records)
        except Exception:
            return {'synced':False,'issue':'Sheets write failed; Calendar appointments remain accepted. Reconcile again.'}
        return {'synced':True,'rows':len(records),'issues':[{'id':k,'issue':v['issue']} for k,v in records.items() if v.get('issue')]}
    def call(self,tool,args):
        self.authorize(tool)
        schemas=ARGUMENTS[tool]
        if not isinstance(args,dict) or set(args)-set(schemas['properties']) or not set(schemas.get('required',[]))<=set(args): raise ValueError('Unknown or missing arguments')
        for k,v in args.items():
            kind=schemas['properties'][k]['type']
            if kind=='string' and (not isinstance(v,str) or len(v)>1000):raise ValueError('Invalid string')
            if kind=='object' and not isinstance(v,dict):raise ValueError('Invalid object')
            if 'enum' in schemas['properties'][k] and v not in schemas['properties'][k]['enum']:raise ValueError('Unknown configured patient')
        if tool=='get_available_slots':return self.slots(args['day'],args.get('preferred_start'))
        if tool=='get_my_appointments':return {'appointments':[public_event(e) for e in self.cal.owned_events(self.identity.clinic,self.identity.subject)]}
        if tool=='book_my_appointment':return self.book(**args)
        if tool=='cancel_my_appointment':return self.change('cancel',args['appointment_id'],token=args.get('confirmation_token'))
        if tool=='reschedule_my_appointment':return self.change('reschedule',args['appointment_id'],args['start'],args.get('confirmation_token'))
        if tool=='get_clinic_information':return {k:self.config[k] for k in ('clinic_name','timezone','address','contact','confirmation_policy','cancellation_policy')}
        if tool=='doctor_book_appointment':
            from mock import MockCalendar
            if not isinstance(self.cal,MockCalendar):raise Denied('Trusted live patient directory not configured')
            patient=Service(Identity(args['patient_reference'],'patient',self.identity.clinic,'synthetic',True),self.cal,self.sheets,self.config)
            patient.pending=self.pending
            return patient.book(args['start'],args['request_id'],args.get('confirmation_token'))
        if tool=='doctor_get_schedule':
            day=date.fromisoformat(args['day']);z=ZoneInfo(self.config['timezone']);a=datetime.combine(day,time(),z)
            return {'appointments':[doctor_event(e) for e in self.cal.schedule(a,a+timedelta(days=1))]}
        if tool=='doctor_get_appointment':return doctor_event(self.managed(args['appointment_id']))
        if tool=='doctor_configure_clinic':
            patch=args['changes']
            if set(patch)-set(DEFAULT) or 'clinic_id' in patch:raise ValueError('Unknown or immutable field')
            c=validate_config(self.config|patch)
            needed=self.confirm('configure',c,args.get('confirmation_token'))
            if needed:return needed
            if self.config_path:atomic(self.config_path,c)
            self.config=c;return {'saved':True,'configuration':c}
        if tool in ('doctor_cancel_appointment','doctor_reschedule_appointment'):
            return self.change('cancel' if tool=='doctor_cancel_appointment' else 'reschedule',args['appointment_id'],args.get('start'),args.get('confirmation_token'),doctor=True)
        if tool=='doctor_block_time':
            a,b=stamp(args['start']),stamp(args['end'])
            if b<=a or b-a>timedelta(days=7):raise ValueError('Invalid block range')
            conflicts=self.cal.schedule(a,b)
            payload={'start':a.isoformat(),'end':b.isoformat(),'conflicts':[doctor_event(e) for e in conflicts]}
            needed=self.confirm('block',payload,args.get('confirmation_token'))
            if needed:return needed
            ident=hashlib.sha256(f'block:{self.identity.clinic}:{a.isoformat()}:{b.isoformat()}'.encode()).hexdigest()
            if not self.cal.get(ident):self.cal.insert({'id':ident,'start':a.isoformat(),'end':b.isoformat(),'status':'confirmed','kind':'block','clinic':self.identity.clinic})
            found=self.cal.get(ident)
            if not found:raise Uncertain('Block unverified')
            return {'calendar_confirmed':True,'block':public_event(found)}
        if tool=='doctor_unblock_time':
            e=self.managed(args['appointment_id'],'block');needed=self.confirm('unblock',public_event(e),args.get('confirmation_token'))
            if needed:return needed
            e['status']='cancelled';self.cal.update(e,e.get('etag'))
            return {'calendar_confirmed':self.cal.get(e['id'])['status']=='cancelled'}
        if tool=='doctor_sync_register':return self.sync()
        if tool=='doctor_sync_status':return self.sheets.status()
        if tool=='doctor_review_issues':return {'register':self.sheets.status(),'schedule_conflicts':self.cal.review_conflicts()}
        if tool=='doctor_open_spreadsheet':return self.sheets.open()
        if tool=='doctor_verify_synthetic_appointment':
            from mock import MockCalendar,MockSheets,fixture
            if not isinstance(self.cal,MockCalendar):raise Denied('Synthetic verification only')
            state=fixture()
            calendar=MockCalendar(state['events']);sheets=MockSheets(fail_next=True)
            patient=Service(Identity('patient-a','patient','synthetic-clinic','synthetic',True),calendar,sheets,state['config'])
            other=Service(Identity('patient-b','patient','synthetic-clinic','synthetic',True),calendar,sheets,state['config'])
            doctor=Service(Identity('synthetic-doctor','doctor','synthetic-clinic','synthetic',True),calendar,sheets,state['config'])
            day=state['events']['a-demo']['start'][:10]
            slot=patient.slots(day)['slots'][0]
            args={'start':slot,'request_id':'synthetic-verification'}
            draft=patient.call('book_my_appointment',args)
            booked=patient.call('book_my_appointment',args|{'confirmation_token':draft['confirmation_token']})
            event_id=booked['appointment']['id']
            failed=doctor.sync();recovered=doctor.sync();count=len(sheets.records);doctor.sync()
            isolated=event_id not in {e['id'] for e in other.call('get_my_appointments',{})['appointments']}
            args={'appointment_id':event_id};draft=patient.call('cancel_my_appointment',args)
            patient.call('cancel_my_appointment',args|{'confirmation_token':draft['confirmation_token']});doctor.sync()
            return {'mode':'isolated-synthetic-verification','calendar_write_verified':booked['calendar_confirmed'],
                'sync_failure_recovered':not failed['synced'] and recovered['synced'],
                'no_duplicate_rows':len(sheets.records)==count,'patient_isolation':isolated,
                'cancellation_synced':sheets.records[event_id]['status']=='cancelled','shared_practice_state_changed':False,'google_accessed':False}
        if tool=='doctor_connection_status':return self.cal.connection_status()
        raise Denied('Unknown operation')

def schema(properties={},required=()):
    return {'type':'object','properties':{k:({'type':v} if isinstance(v,str) else v) for k,v in properties.items()},'required':list(required),'additionalProperties':False}
ARGUMENTS={
 'get_available_slots':schema({'day':'string','preferred_start':'string'},['day']), 'get_my_appointments':schema(),
 'get_clinic_information':schema(),
 'book_my_appointment':schema({'start':'string','request_id':'string','confirmation_token':'string'},['start','request_id']),
 'cancel_my_appointment':schema({'appointment_id':'string','confirmation_token':'string'},['appointment_id']),
 'reschedule_my_appointment':schema({'appointment_id':'string','start':'string','confirmation_token':'string'},['appointment_id','start']),
 'doctor_book_appointment':schema({'patient_reference':{'type':'string','enum':['patient-a','patient-b']},'start':'string','request_id':'string','confirmation_token':'string'},['patient_reference','start','request_id']),
 'doctor_get_schedule':schema({'day':'string'},['day']),
 'doctor_get_appointment':schema({'appointment_id':'string'},['appointment_id']),
 'doctor_configure_clinic':schema({'changes':'object','confirmation_token':'string'},['changes']),
 'doctor_block_time':schema({'start':'string','end':'string','confirmation_token':'string'},['start','end']),
 'doctor_unblock_time':schema({'appointment_id':'string','confirmation_token':'string'},['appointment_id']),
 'doctor_cancel_appointment':schema({'appointment_id':'string','confirmation_token':'string'},['appointment_id']),
 'doctor_reschedule_appointment':schema({'appointment_id':'string','start':'string','confirmation_token':'string'},['appointment_id','start']),
 **{k:schema() for k in ('doctor_sync_register','doctor_sync_status','doctor_review_issues','doctor_open_spreadsheet','doctor_connection_status','doctor_verify_synthetic_appointment')}
}
