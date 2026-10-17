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
          'doctor_review_issues','doctor_open_spreadsheet','doctor_connection_status','doctor_verify_synthetic_appointment','doctor_book_appointment',
          'doctor_get_clinic_settings'}

DEFAULT = dict(clinic_id='synthetic-clinic', clinic_name='Practice Clinic', timezone='Asia/Kolkata',
    working_days=[0,1,2,3,4,5], opening='09:00', closing='17:00', breaks=[['13:00','14:00']],
    duration_minutes=30, buffer_minutes=10, address='Synthetic address', contact='Synthetic contact',
    calendar_id='', spreadsheet_id='', confirmation_policy='Confirm the selected slot before booking.',
    cancellation_policy='Confirm cancellation before submitting.',
    # 'slots': patients pick a set start time. 'count': the doctor caps how many
    # consultations and follow-ups a day takes; patients book a place that day.
    booking_mode='slots', daily_caps={'consultation':10,'follow_up':5}, day_caps={})
CATEGORIES=('consultation','follow_up')
COUNT_FIELDS=('booking_mode','daily_caps','day_caps')

def valid_caps(caps,partial=False):
    if not isinstance(caps,dict) or set(caps)-set(CATEGORIES) or (not partial and set(caps)!=set(CATEGORIES)):raise ValueError('Caps need consultation and follow_up counts')
    if any(type(v) is not int or not 0<=v<=500 for v in caps.values()):raise ValueError('Caps must be whole numbers from 0 to 500')

def validate_config(c):
    c = {k:copy.deepcopy(DEFAULT[k]) for k in COUNT_FIELDS if k not in c} | c  # configs saved before count mode
    if set(c) != set(DEFAULT): raise ValueError('Unknown or missing configuration fields')
    if c['booking_mode'] not in ('slots','count'): raise ValueError('Booking mode must be slots or count')
    valid_caps(c['daily_caps'])
    if not isinstance(c['day_caps'],dict): raise ValueError('Invalid day caps')
    for d,caps in c['day_caps'].items():
        if not isinstance(d,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',d): raise ValueError('Day caps need YYYY-MM-DD dates')
        date.fromisoformat(d); valid_caps(caps,partial=True)
    ZoneInfo(c['timezone'])
    for k in ('duration_minutes','buffer_minutes'):
        if type(c[k]) is not int or not 0 <= c[k] <= 240: raise ValueError('Invalid duration/buffer')
    if c['duration_minutes'] < 5: raise ValueError('Minimum duration is 5 minutes')
    if not c['working_days'] or any(type(x) is not int or x not in range(7) for x in c['working_days']): raise ValueError('Invalid working days')
    if time.fromisoformat(c['opening']) >= time.fromisoformat(c['closing']): raise ValueError('Invalid hours')
    for a,b in c['breaks']:
        if not time.fromisoformat(c['opening']) <= time.fromisoformat(a) < time.fromisoformat(b) <= time.fromisoformat(c['closing']): raise ValueError('Invalid break')
    for k,v in c.items():
        if k not in ('working_days','breaks','duration_minutes','buffer_minutes')+COUNT_FIELDS:
            if not isinstance(v,str) or len(v)>500: raise ValueError('Invalid configuration text')
    if c['calendar_id']=='primary': raise ValueError('Select an explicit clinic calendar ID')
    if c['spreadsheet_id'] and not re.fullmatch(r'[A-Za-z0-9_-]{10,200}',c['spreadsheet_id']): raise ValueError('Invalid spreadsheet ID')
    return c

def public_event(e):
    # No raw event summary/description/contact data reaches an agent.
    return {k:copy.deepcopy(e[k]) for k in ('id','start','end','status','kind','mode','category') if k in e}

# What the patient last agreed to, kept on the event so any change made by the
# clinic (doctor assistant, or editing/deleting directly in Google Calendar) shows
# up as a notice. NOT_AGREED marks an appointment the clinic booked for them.
NOT_AGREED='clinic-booked'
def agreed_state(e):return '|'.join((e['start'],e['end'],e['status']))

def clinic_change(e):
    agreed=e.get('agreed')
    if e.get('kind')!='appointment' or 'start' not in e:return None
    if agreed is None:  # booked before change tracking: only a direct deletion is detectable
        return {'type':'cancelled_by_clinic'} if e.get('status')=='cancelled' and e.get('clinic_status')=='confirmed' else None
    if agreed==NOT_AGREED:return {'type':'cancelled_by_clinic' if e['status']=='cancelled' else 'booked_by_clinic'}
    if agreed==agreed_state(e):return None
    was,was_end,was_status=agreed.split('|')
    if e['status']=='cancelled' and was_status!='cancelled':return {'type':'cancelled_by_clinic','previous_start':was}
    if e['start']!=was or e['end']!=was_end:return {'type':'moved_by_clinic','previous_start':was,'previous_end':was_end}
    return None

def notice_key(e):
    change=e.get('clinic_change') or clinic_change(e)
    return '|'.join((e['id'],change['type'],e['start'],e.get('end',''),e['status']))

class NoticeLog:
    """Clinic-change notices already delivered, per patient, in a local file."""
    def __init__(self,path):self.path=Path(path)
    def load(self,patient):
        try:return set(json.loads(self.path.read_text()).get(patient,[]))
        except (OSError,ValueError):return set()
    def add(self,patient,keys):
        with lock(self.path.with_suffix('.lock')):
            try:data=json.loads(self.path.read_text())
            except (OSError,ValueError):data={}
            data[patient]=sorted(set(data.get(patient,[]))|set(keys))[-500:];atomic(self.path,data)

class AlertLog:
    """Doctor alerts (a day's cap reached), kept in a local file. Each record is
    shown once in the Doctor Assistant; an outside messenger can read the same file."""
    def __init__(self,path):self.path=Path(path)
    def _load(self):
        try:return json.loads(self.path.read_text())
        except (OSError,ValueError):return []
    def raise_alert(self,day,category,cap,booked):
        with lock(self.path.with_suffix('.lock')):
            alerts=self._load()
            if any(a['day']==day and a['category']==category and a['cap']==cap for a in alerts):return
            alerts.append({'id':secrets.token_hex(8),'created':datetime.now().astimezone().isoformat(),'day':day,'category':category,
                           'cap':cap,'booked':booked,'delivered_in_assistant':False})
            atomic(self.path,alerts[-500:])
    def pending(self):return [a for a in self._load() if not a['delivered_in_assistant']]
    def deliver(self):
        with lock(self.path.with_suffix('.lock')):
            alerts=self._load();due=[a for a in alerts if not a['delivered_in_assistant']]
            for a in due:a['delivered_in_assistant']=True
            if due:atomic(self.path,alerts)
            return due

def patient_event(e):
    result=public_event(e);change=clinic_change(e)
    if change:result['clinic_change']=change
    return result

def doctor_event(e):
    result=public_event(e)
    if e.get("kind")=="appointment" and e.get("owner"):
        result["patient_reference"]=e["owner"]
    return result

class Service:
    def __init__(self, identity, calendar, sheets, config=None, config_path=None, approver=None, synthetic_directory=False):
        self.identity, self.cal, self.sheets = identity, calendar, sheets
        self.config = validate_config(copy.deepcopy(config or DEFAULT))
        self.config_path = config_path
        self.pending = {}
        # approver: trusted out-of-band human confirmation (live mode). The model
        # can relay a token but cannot answer the approver's channel.
        self.approver = approver
        # Live Google mode with the configured synthetic Patient A/B directory.
        self.synthetic_directory = synthetic_directory
        self.booked_by_clinic = False
        self.notices_seen = None  # NoticeLog in running sessions: each clinic change is told once
        self.alerts = None  # AlertLog in running sessions: a reached cap is told to the doctor once
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
        if self.approver is not None and self.approver(action,payload) is not True: raise Denied('Not approved in the independent confirmation dialog; nothing was changed')
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
    def grid(self, d):
        """Every appointment start the clinic offers on day d: from opening and again
        after each break, one appointment plus buffer apart. Patients book only these."""
        z=ZoneInfo(self.config['timezone']); c=self.config
        length=timedelta(minutes=c['duration_minutes']); step=length+timedelta(minutes=c['buffer_minutes'])
        def at(v):return datetime.combine(d,time.fromisoformat(v),z)
        starts=[]
        for begin in sorted({c['opening'],*(y for x,y in c['breaks'])}):
            a=at(begin)
            if not at(c['opening'])<=a<at(c['closing']):continue
            while a+length<=at(c['closing']) and self.valid_hours(a,a+length):
                starts.append(a);a+=step
        return sorted(set(starts))
    def on_grid(self, a):return a in self.grid(a.date())
    def count_mode(self):return self.config['booking_mode']=='count'
    def caps_for(self,d):return self.config['daily_caps']|self.config['day_caps'].get(d.isoformat(),{})
    def window(self,d):
        z=ZoneInfo(self.config['timezone'])
        return datetime.combine(d,time.fromisoformat(self.config['opening']),z),datetime.combine(d,time.fromisoformat(self.config['closing']),z)
    def parse_day(self,start):
        return date.fromisoformat(start) if len(start)==10 else stamp(start).astimezone(ZoneInfo(self.config['timezone'])).date()
    def day_open(self,d):
        a,b=self.window(d)
        if d.weekday() not in self.config['working_days'] or b<=datetime.now(a.tzinfo):return False
        # A block covering the whole working day closes it; partial blocks do not.
        return not any(e['kind']=='block' and stamp(e['start'])<=a and stamp(e['end'])>=b for e in self.cal.schedule(a,b))
    def day_bookings(self,d,category=None,exclude=None):
        a,b=self.window(d)
        return [e for e in self.cal.schedule(a,b) if e.get('mode')=='count' and e['kind']=='appointment' and e['status']!='cancelled'
                and e['id']!=exclude and (category is None or e.get('category')==category)]
    def places(self,d,exclude=None):
        caps=self.caps_for(d);out={}
        for cat in CATEGORIES:
            booked=len(self.day_bookings(d,cat,exclude));out[cat]={'cap':caps[cat],'booked':booked,'open':max(0,caps[cat]-booked)}
        return out
    def open_days(self,category,after,limit=5):
        days,d=[],after
        for _ in range(21):
            d+=timedelta(days=1)
            if self.day_open(d) and self.places(d)[category]['open']>0:days.append(d.isoformat())
            if len(days)>=limit:break
        return days
    def alert_if_full(self,d,category):
        p=self.places(d)[category]
        if self.alerts is not None and p['booked']>=p['cap']:self.alerts.raise_alert(d.isoformat(),category,p['cap'],p['booked'])
    def book_count(self,start,request_id,confirmation_token=None,category=None,allow_over_cap=False):
        d=self.parse_day(start)
        ident=hashlib.sha256(f'{self.identity.clinic}:{self.identity.subject}:{request_id}'.encode()).hexdigest()
        a,b=self.window(d)
        existing=self.cal.get(ident)
        if existing:
            if existing.get('owner')!=self.identity.subject or existing.get('start')!=a.isoformat(): raise Conflict('Request ID reused for different appointment')
            return {'calendar_confirmed':True,'appointment':public_event(existing)}
        if not self.day_open(d):return {'conflict':True,'closed':True,'reason':'The clinic is not taking bookings that day.','alternatives':self.open_days(category or 'consultation',d)}
        if category is None:
            history=[e for e in self.cal.owned_events(self.identity.clinic,self.identity.subject) if e['kind']=='appointment' and e['status']!='cancelled']
            if not history:return {'category_required':True,'question':'Is this a first consultation or a follow-up visit?'}
            category='follow_up'
        over=lambda:self.places(d)[category]['open']<=0 and not (self.booked_by_clinic and allow_over_cap)
        full=lambda:{'conflict':True,'full':True,'day':d.isoformat(),'category':category,'alternatives':self.open_days(category,d)}
        if over():return full()
        draft={'id':ident,'start':a.isoformat(),'end':b.isoformat(),'status':'confirmed','kind':'appointment','mode':'count','category':category,
               'owner':self.identity.subject,'clinic':self.identity.clinic}
        draft['agreed']=NOT_AGREED if self.booked_by_clinic else agreed_state(draft)
        needed=self.confirm('book',draft,confirmation_token)
        if needed:return needed
        if over():return full()  # recheck immediately before the write
        try:self.cal.insert(draft)
        except (TimeoutError,Uncertain):
            found=self.cal.get(ident)
            if not found or any(found.get(k)!=v for k,v in draft.items()): raise Uncertain('Write unresolved; retry SAME request ID. Do not confirm booking.')
        found=self.cal.get(ident)
        if not found or any(found.get(k)!=v for k,v in draft.items()): raise Uncertain('Calendar verification failed')
        self.alert_if_full(d,category)
        return {'calendar_confirmed':True,'appointment':public_event(found),'sheets_status':'pending'}
    def slots(self, day, preferred_start=None):
        d=date.fromisoformat(day); z=ZoneInfo(self.config['timezone']); c=self.config
        if self.count_mode():
            result={'mode':'count','day':day,'timezone':c['timezone'],'places':self.places(d)}
            if not self.day_open(d):result['closed']=True
            return result
        length=timedelta(minutes=c['duration_minutes'])
        slots=[a.isoformat() for a in self.grid(d) if a>datetime.now(z) and self.available(a,a+length)]
        result={'slots':slots,'timezone':c['timezone']}
        if preferred_start:
            preferred=stamp(preferred_start).astimezone(z)
            if preferred.date()!=d:raise ValueError('Requested start must match day in clinic timezone')
            # Only listed slots can be booked; say why another time cannot be, so the
            # assistant never calls a free time between slots "booked".
            result['requested_start_available']=preferred.isoformat() in slots
            if preferred.isoformat() in slots:status='available'
            elif not self.valid_hours(preferred,preferred+length):status='outside_clinic_hours'
            elif not self.on_grid(preferred):status='not_a_clinic_appointment_time'
            elif preferred<=datetime.now(z):status='in_the_past'
            else:status='already_booked'
            result['requested_start_status']=status
        return result
    def book(self,start,request_id,confirmation_token=None,category=None,allow_over_cap=False):
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',request_id): raise ValueError('Request ID must contain 8–100 safe characters')
        if self.count_mode():return self.book_count(start,request_id,confirmation_token,category,allow_over_cap)
        a,b=self.interval(start)
        ident=hashlib.sha256(f'{self.identity.clinic}:{self.identity.subject}:{request_id}'.encode()).hexdigest()
        existing=self.cal.get(ident)
        if existing:
            if existing.get('owner')!=self.identity.subject or existing.get('start')!=a.isoformat(): raise Conflict('Request ID reused for different appointment')
            return {'calendar_confirmed':True,'appointment':public_event(existing)}
        if not self.booked_by_clinic and not self.on_grid(a): return {'conflict':True,'requested_start_status':'not_a_clinic_appointment_time','reason':'Not one of the clinic\'s appointment times (the time itself is free or unknown, not booked); offer one of the alternatives.','alternatives':self.slots(a.date().isoformat())}
        if not self.available(a,b): return {'conflict':True,'alternatives':self.slots(a.date().isoformat())}
        draft={'id':ident,'start':a.isoformat(),'end':b.isoformat(),'status':'confirmed','kind':'appointment','owner':self.identity.subject,'clinic':self.identity.clinic}
        draft['agreed']=NOT_AGREED if self.booked_by_clinic else agreed_state(draft)
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
        day=None
        if start and e.get('mode')=='count':
            day=self.parse_day(start);a,b=self.window(day);payload['start']=a.isoformat()
            if not self.day_open(day):return {'conflict':True,'closed':True,'alternatives':self.open_days(e['category'],day)}
            if self.places(day,exclude=ident)[e['category']]['open']<=0:return {'conflict':True,'full':True,'day':day.isoformat(),'category':e['category'],'alternatives':self.open_days(e['category'],day)}
        elif start:
            a,b=self.interval(start);payload['start']=a.isoformat()
            if not doctor and not self.on_grid(a):return {'conflict':True,'requested_start_status':'not_a_clinic_appointment_time','reason':'Not one of the clinic\'s appointment times (the time itself is free or unknown, not booked); offer one of the alternatives.','alternatives':self.slots(a.date().isoformat())}
            if not self.available(a,b,ident):return {'conflict':True,'alternatives':self.slots(a.date().isoformat())}
        needed=self.confirm(action,payload,token)
        if needed:return needed
        updated=copy.deepcopy(e)
        if action=='cancel':updated['status']='cancelled'
        else:updated.update(start=a.isoformat(),end=b.isoformat())
        if not doctor:updated['agreed']=agreed_state(updated)  # the patient made this change
        elif 'agreed' not in e and e.get('kind')=='appointment':updated['agreed']=agreed_state(e)  # booked before tracking
        try:self.cal.update(updated,e.get('etag'))
        except (TimeoutError,Uncertain):pass
        found=self.cal.get(ident)
        # Google may return a cancelled event without its times; status alone proves a cancellation.
        if not found or any(found.get(k)!=updated.get(k) for k in (('status',) if action=='cancel' else ('start','end','status'))): raise Uncertain('Change unverified; retry after reviewing Calendar')
        if day:self.alert_if_full(day,e['category'])
        return {'calendar_confirmed':True,'appointment':public_event(found)}
    def sync(self):
        # Register is reporting state, never read by scheduling operations.
        records=self.sheets.read_records(); seen=set()
        for e in self.cal.managed_events(self.identity.clinic):
            if e.get('kind')!='appointment':continue
            seen.add(e['id']); records[e['id']]=records.get(e['id'],{})|(public_event(e) if 'start' in e and 'end' in e else {'status':e['status']})|{'last_seen':datetime.now().isoformat(),'issue':''}
        for ident,row in records.items():
            if ident not in seen and row.get('status')!='cancelled': row['issue']='missing_from_calendar_review_required'
        try:self.sheets.write_records(records)
        except Exception:
            return {'synced':False,'issue':'Sheets write failed; Calendar appointments remain accepted. Reconcile again.'}
        return {'synced':True,'rows':len(records),'issues':[{'id':k,'issue':v['issue']} for k,v in records.items() if v.get('issue')]}
    def call(self,tool,args):
        result=self.handle(tool,args)
        if self.identity.role=='patient' and isinstance(result,dict):
            # Every patient answer carries upcoming clinic changes. The start-up
            # banner (tools/notices.py) is the channel the model cannot skip.
            now=datetime.now(ZoneInfo("UTC"))
            changed=[e for e in self.cal.owned_events(self.identity.clinic,self.identity.subject) if clinic_change(e) and stamp(e['start'])>now]
            if self.notices_seen is not None:
                # Each change is told once: skip what the start-up message or an
                # earlier answer already delivered.
                seen=self.notices_seen.load(self.identity.subject)
                changed=[e for e in changed if notice_key(e) not in seen]
                if changed:self.notices_seen.add(self.identity.subject,[notice_key(e) for e in changed])
            if changed:result={'tell_patient_first':[self.notice(e) for e in changed]}|result
        if self.identity.role=='doctor' and self.alerts is not None and isinstance(result,dict):
            told=[]
            for a in self.alerts.deliver():
                d=date.fromisoformat(a['day']);p=self.places(d)[a['category']]
                if p['booked']<p['cap'] or d<datetime.now(ZoneInfo(self.config['timezone'])).date():continue  # reopened or past since
                label='consultation' if a['category']=='consultation' else 'follow-up'
                told.append(f"{d.strftime('%a %d %b')}: {p['booked']} of {p['cap']} {label} places are booked, so patients asking for that day are being turned away. Ask the doctor whether to accept more {label}s that day (and how many) or keep it closed.")
            if told:result={'tell_doctor_first':told}|result
        return result
    def notice(self,e):
        """Plain sentence about a clinic-side change, in clinic time."""
        z=ZoneInfo(self.config['timezone'])
        def when(v):
            t=stamp(v).astimezone(z);return t.strftime('%a %d %b, ')+t.strftime('%I:%M %p').lstrip('0').lower()
        change=clinic_change(e) or e.get('clinic_change')
        if e.get('mode')=='count':  # a place for the day: name days, never times
            day=lambda v:stamp(v).astimezone(z).strftime('%a %d %b')
            if change['type']=='moved_by_clinic':return 'The clinic moved your appointment from '+day(change['previous_start'])+' to '+day(e['start'])+'.'
            if change['type']=='cancelled_by_clinic':return 'The clinic cancelled your appointment on '+day(e['start'])+'.'
            return 'The clinic booked a place for you on '+day(e['start'])+'.'
        if change['type']=='moved_by_clinic':
            return 'The clinic changed your appointment from '+when(change['previous_start'])+'–'+when(change.get('previous_end',change['previous_start'])).split(', ')[-1]+' to '+when(e['start'])+'–'+when(e['end']).split(', ')[-1]+'.'
        if change['type']=='cancelled_by_clinic':return 'The clinic cancelled your appointment on '+when(e['start'])+'.'
        return 'The clinic booked an appointment for you on '+when(e['start'])+'.'
    def handle(self,tool,args):
        self.authorize(tool)
        schemas=ARGUMENTS[tool]
        if not isinstance(args,dict) or set(args)-set(schemas['properties']) or not set(schemas.get('required',[]))<=set(args): raise ValueError('Unknown or missing arguments')
        for k,v in args.items():
            kind=schemas['properties'][k]['type']
            if kind=='string' and (not isinstance(v,str) or len(v)>1000):raise ValueError('Invalid string')
            if kind=='object' and not isinstance(v,dict):raise ValueError('Invalid object')
            if 'enum' in schemas['properties'][k] and v not in schemas['properties'][k]['enum']:raise ValueError('Unknown configured patient')
        if tool=='get_available_slots':return self.slots(args['day'],args.get('preferred_start'))
        if tool=='get_my_appointments':return {'appointments':[patient_event(e) for e in self.cal.owned_events(self.identity.clinic,self.identity.subject)]}
        if tool=='book_my_appointment':return self.book(**args)
        if tool=='cancel_my_appointment':return self.change('cancel',args['appointment_id'],token=args.get('confirmation_token'))
        if tool=='reschedule_my_appointment':return self.change('reschedule',args['appointment_id'],args['start'],args.get('confirmation_token'))
        if tool in ('get_clinic_information','doctor_get_clinic_settings'):
            public=('clinic_name','timezone','working_days','opening','closing','breaks','duration_minutes','buffer_minutes','address','contact','confirmation_policy','cancellation_policy','booking_mode')
            if tool=='doctor_get_clinic_settings':public+=('daily_caps','day_caps')
            return copy.deepcopy({k:self.config[k] for k in public})|{'clinic_today':datetime.now(ZoneInfo(self.config['timezone'])).date().isoformat()}
        if tool=='doctor_book_appointment':
            from mock import MockCalendar
            if not (isinstance(self.cal,MockCalendar) or self.synthetic_directory):raise Denied('Trusted live patient directory not configured')
            patient=Service(Identity(args['patient_reference'],'patient',self.identity.clinic,'synthetic',True),self.cal,self.sheets,self.config,approver=self.approver)
            patient.pending=self.pending;patient.booked_by_clinic=True;patient.alerts=self.alerts
            return patient.book(args['start'],args['request_id'],args.get('confirmation_token'),args.get('category'),args.get('allow_over_cap') is True)
        if tool=='doctor_get_schedule':
            day=date.fromisoformat(args['day']);z=ZoneInfo(self.config['timezone']);a=datetime.combine(day,time(),z)
            result={'appointments':[doctor_event(e) for e in self.cal.schedule(a,a+timedelta(days=1))]}
            if self.count_mode():result['places']=self.places(day)
            return result
        if tool=='doctor_get_appointment':return doctor_event(self.managed(args['appointment_id']))
        if tool=='doctor_configure_clinic':
            patch=args['changes']
            if set(patch)-set(DEFAULT) or set(patch)&SETUP_ONLY:raise ValueError('Unknown or immutable field')
            if 'day_caps' in patch:  # one day's change keeps every other day's; null removes a day
                base=patch.get('daily_caps',self.config['daily_caps']);today=datetime.now(ZoneInfo(self.config['timezone'])).date().isoformat()
                merged={d:v for d,v in self.config['day_caps'].items() if d>=today}
                for d,v in patch['day_caps'].items():
                    if v is None:merged.pop(d,None)
                    else:valid_caps(v,partial=True);merged[d]=base|merged.get(d,{})|v
                patch=patch|{'day_caps':merged}
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

# Bound by trusted setup and live activation; agents can never redirect resources.
SETUP_ONLY={'clinic_id','calendar_id','spreadsheet_id'}

def schema(properties={},required=()):
    return {'type':'object','properties':{k:({'type':v} if isinstance(v,str) else v) for k,v in properties.items()},'required':list(required),'additionalProperties':False}
CONFIG_CHANGES=schema({
    **{k:{'type':'string'} for k in DEFAULT if k not in SETUP_ONLY|{'working_days','breaks','duration_minutes','buffer_minutes'}},
    'working_days':{'type':'array','items':{'type':'integer','minimum':0,'maximum':6},'minItems':1,'description':'Monday=0 through Sunday=6.'},
    'breaks':{'type':'array','items':{'type':'array','items':{'type':'string'},'minItems':2,'maxItems':2},'description':'Pairs of local HH:MM start/end times.'},
    'duration_minutes':{'type':'integer','minimum':5,'maximum':240,'description':'Appointment length in minutes.'},
    'buffer_minutes':{'type':'integer','minimum':0,'maximum':240,'description':'Symmetric clearance before AND after each appointment. Five minutes before and after means 5, not 10. Separate before/after settings are unsupported.'},
    'booking_mode':{'type':'string','enum':['slots','count'],'description':'slots: patients pick set start times. count: no times; the doctor caps how many consultations and follow-ups each day takes.'},
    'daily_caps':{'type':'object','properties':{c:{'type':'integer','minimum':0,'maximum':500} for c in CATEGORIES},'required':list(CATEGORIES),'additionalProperties':False,'description':'Usual places per working day in count mode.'},
    'day_caps':{'type':'object','additionalProperties':{'type':['object','null'],'properties':{c:{'type':'integer','minimum':0,'maximum':500} for c in CATEGORIES},'additionalProperties':False},'description':'Per-day overrides keyed YYYY-MM-DD, e.g. {"2026-10-20":{"consultation":15}}. Only the days given change; null removes a day.'}
})
ARGUMENTS={
 'get_available_slots':schema({'day':'string','preferred_start':'string'},['day']), 'get_my_appointments':schema(),
 'get_clinic_information':schema(),
 'book_my_appointment':schema({'start':{'type':'string','description':'Slot mode: the exact slot start with offset. Count mode: the day, YYYY-MM-DD.'},'request_id':'string','confirmation_token':'string','category':{'type':'string','enum':list(CATEGORIES),'description':'Count mode only. Omit for a returning patient (follow_up is inferred); ask a new patient.'}},['start','request_id']),
 'cancel_my_appointment':schema({'appointment_id':'string','confirmation_token':'string'},['appointment_id']),
 'reschedule_my_appointment':schema({'appointment_id':'string','start':'string','confirmation_token':'string'},['appointment_id','start']),
 'doctor_book_appointment':schema({'patient_reference':{'type':'string','enum':['patient-a','patient-b']},'start':'string','request_id':'string','confirmation_token':'string','category':{'type':'string','enum':list(CATEGORIES)},'allow_over_cap':{'type':'boolean','description':'Count mode: book even though the day is full. Only after the doctor explicitly agrees.'}},['patient_reference','start','request_id']),
 'doctor_get_schedule':schema({'day':'string'},['day']),
 'doctor_get_appointment':schema({'appointment_id':'string'},['appointment_id']),
 'doctor_configure_clinic':schema({'changes':CONFIG_CHANGES,'confirmation_token':'string'},['changes']),
 'doctor_block_time':schema({'start':'string','end':'string','confirmation_token':'string'},['start','end']),
 'doctor_unblock_time':schema({'appointment_id':'string','confirmation_token':'string'},['appointment_id']),
 'doctor_cancel_appointment':schema({'appointment_id':'string','confirmation_token':'string'},['appointment_id']),
 'doctor_reschedule_appointment':schema({'appointment_id':'string','start':'string','confirmation_token':'string'},['appointment_id','start']),
 **{k:schema() for k in ('doctor_sync_register','doctor_sync_status','doctor_review_issues','doctor_open_spreadsheet','doctor_connection_status','doctor_verify_synthetic_appointment','doctor_get_clinic_settings')}
}
