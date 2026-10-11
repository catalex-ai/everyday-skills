"""Separate synthetic Calendar and reporting fixtures; never imports Google."""
import copy
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from core import DEFAULT, stamp, atomic

class MockCalendar:
    def __init__(self,events=None):self.events=copy.deepcopy(events or {});self.timeout_insert=False;self.timeout_update=False;self.before_insert=None
    def verify(self):return True
    def get(self,ident):return copy.deepcopy(self.events.get(ident))
    def insert(self,e):
        if self.before_insert:self.before_insert(self,e)
        if e['id'] in self.events:raise ValueError('Duplicate ID')
        self.events[e['id']]=copy.deepcopy(e)
        if self.timeout_insert:raise TimeoutError()
    def update(self,e,etag=None):
        self.events[e['id']]=copy.deepcopy(e)
        if self.timeout_update:raise TimeoutError()
    def owned_events(self,clinic,owner):
        return [copy.deepcopy(e) for e in self.events.values() if e.get('owner')==owner and e.get('clinic')==clinic]
    def managed_events(self,clinic):return [copy.deepcopy(e) for e in self.events.values() if e.get('clinic')==clinic]
    def schedule(self,a,b):return [copy.deepcopy(e) for e in self.events.values() if e['status']!='cancelled' and stamp(e['start'])<b and stamp(e['end'])>a]
    def busy(self,a,b,exclude=None):return [(e['start'],e['end']) for e in self.schedule(a,b) if e['id']!=exclude]
    def review_conflicts(self):
        ev=[e for e in self.events.values() if e['status']!='cancelled'];out=[]
        for i,e in enumerate(ev):
            for f in ev[i+1:]:
                if stamp(e['start'])<stamp(f['end']) and stamp(f['start'])<stamp(e['end']):out.append([e['id'],f['id']])
        return out
    def connection_status(self):return {'mode':'practice','google_connected':False}

class MockSheets:
    def __init__(self,records=None,fail_next=False):self.records=copy.deepcopy(records or {});self.fail_next=fail_next;self.last='never'
    def verify(self):return True
    def read_records(self):return copy.deepcopy(self.records)
    def write_records(self,records):
        if self.fail_next:self.fail_next=False;self.last='failed';raise OSError('Synthetic failure')
        self.records=copy.deepcopy(records);self.last='success'
    def status(self):return {'mode':'practice','last_sync':self.last,'rows':len(self.records),'issues':[k for k,v in self.records.items() if v.get('issue')]}
    def open(self):return {'opened':False,'reason':'Practice mode has no real spreadsheet'}

def fixture():
    d=datetime.now(ZoneInfo(DEFAULT['timezone'])).date()+timedelta(days=1)
    while d.weekday() not in DEFAULT['working_days']:d+=timedelta(days=1)
    events={}
    for ident,owner,start,end,kind,status in [('a-demo','patient-a',9,9.5,'appointment','confirmed'),('b-demo','patient-b',10,10.5,'appointment','confirmed'),('blocked-demo',None,11,12,'block','confirmed'),('cancelled-demo','patient-a',15,15.5,'appointment','cancelled')]:
        base=datetime.combine(d,datetime.min.time(),ZoneInfo(DEFAULT['timezone']))
        e={'id':ident,'owner':owner,'clinic':DEFAULT['clinic_id'],'start':(base+timedelta(hours=start)).isoformat(),'end':(base+timedelta(hours=end)).isoformat(),'kind':kind,'status':status}
        events[ident]=e
    return {'config':copy.deepcopy(DEFAULT),'events':events,'records':{},'fail_next':True,'last_sync':'never'}
