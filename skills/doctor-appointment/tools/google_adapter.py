"""Direct official Google APIs, used only inside the trusted helper boundary."""
import json, webbrowser, hashlib
from datetime import datetime,timedelta
from urllib.parse import quote
from core import stamp, Conflict, Uncertain
SCOPES=['https://www.googleapis.com/auth/calendar.events','https://www.googleapis.com/auth/calendar.readonly','https://www.googleapis.com/auth/spreadsheets']
SERVICE='CatalEx.DoctorAssistant.Google'
ACCOUNT='clinic-application'

def keychain():
    import keyring
    from keyring.backends.macOS import Keyring
    backend=keyring.get_keyring()
    if not isinstance(backend,Keyring):raise RuntimeError('macOS Keychain required; no plaintext fallback')
    return backend

def credentials():
    from google.oauth2.credentials import Credentials
    value=keychain().get_password(SERVICE,ACCOUNT)
    if not value:raise RuntimeError('Google is not connected')
    return Credentials.from_authorized_user_info(json.loads(value),SCOPES)

def authorize(client_path):
    """Terminal-only installed-app consent; credentials never become tool output."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    keychain() # Fail before opening a browser if secure storage is unavailable.
    client=json.loads(client_path.read_text())
    if 'installed' not in client:raise ValueError('Google OAuth Desktop app client required')
    flow=InstalledAppFlow.from_client_config(client,SCOPES)
    creds=flow.run_local_server(host='127.0.0.1',port=0,open_browser=True,timeout_seconds=180,
        authorization_prompt_message='Approve Google access in the browser: {url}',
        success_message='Authorization complete. Return to your terminal.',access_type='offline',prompt='consent')
    if not creds.refresh_token:raise RuntimeError('No refresh token issued; consent did not complete')
    return creds

def store_credentials(creds):
    keychain().set_password(SERVICE,ACCOUNT,creds.to_json())

def connect(client_path,calendar_id,spreadsheet_id):
    if not calendar_id or calendar_id=='primary' or not spreadsheet_id:raise ValueError('Explicit calendar and spreadsheet IDs required')
    creds=authorize(client_path)
    Calendar(creds,calendar_id).verify()
    Sheets(creds,spreadsheet_id).verify()
    store_credentials(creds)
    return {'connected':True,'calendar_verified':True,'spreadsheet_verified':True}

def list_calendars(creds):
    """Setup-only writable calendar metadata for human selection; no events."""
    from googleapiclient.discovery import build
    api=build('calendar','v3',credentials=creds,cache_discovery=False)
    result=[];token=None
    while True:
        page=api.calendarList().list(minAccessRole='writer',maxResults=250,pageToken=token,showDeleted=False).execute()
        result.extend({k:c[k] for k in ('id','summary','accessRole','primary') if k in c}
                      for c in page.get('items',[]) if c.get('accessRole') in ('writer','owner') and c.get('id')!='primary')
        token=page.get('nextPageToken')
        if not token:return result

def revoke():
    import requests
    backend=keychain();raw=backend.get_password(SERVICE,ACCOUNT)
    if not raw:return {'removed':True,'revoked':False,'reason':'No stored authorization'}
    token=json.loads(raw).get('refresh_token')
    response=requests.post('https://oauth2.googleapis.com/revoke',data={'token':token},timeout=30)
    if response.status_code!=200:raise RuntimeError('Revocation failed; stored credential retained for retry')
    backend.delete_password(SERVICE,ACCOUNT)
    return {'revoked':True,'removed':True}

class Calendar:
    def __init__(self,creds,calendar_id):
        from googleapiclient.discovery import build
        if not calendar_id or calendar_id=='primary':raise ValueError('Explicit calendar ID required')
        self.api=build('calendar','v3',credentials=creds,cache_discovery=False);self.calendar_id=calendar_id
    def verify(self):
        self.api.calendars().get(calendarId=self.calendar_id).execute()
        # Read verification cannot prove write permission without a consented write.
    def connection_status(self):self.verify();return {'mode':'google','calendar_read_verified':True,'write_verified':False}
    @staticmethod
    def decode(e):
        p=e.get('extendedProperties',{}).get('private',{})
        result={'id':e['id'],'status':'cancelled' if e.get('status')=='cancelled' else p.get('clinicStatus',e.get('status','confirmed')),'kind':p.get('kind','external'),
            'clinic':p.get('clinic'),'owner':p.get('owner'),'etag':e.get('etag'),'clinic_status':p.get('clinicStatus')}
        for k in ('agreed','mode','category'):
            if k in p:result[k]=p[k]
        for k in ('start','end'):
            v=e.get(k,{})
            if 'dateTime' in v:result[k]=v['dateTime']
            elif 'date' in v:result[k]=v['date']+'T00:00:00+00:00' # normalized below in list
        return result
    @staticmethod
    def encode(e):
        private = {k:e[k] for k in ('clinic','kind','owner','agreed','mode','category') if e.get(k)}
        private['clinicStatus'] = e['status']
        if e.get('owner'):
            private['patientScope'] = Calendar.patient_scope(e['clinic'],e['owner'])
        return {
            'id':e['id'],
            'summary':'Synthetic appointment' if e['kind']=='appointment' else 'Clinic unavailable',
            # Google status cancelled removes it from the calendar view (it stays
            # retrievable by ID); a visible "free" event looks booked to the doctor.
            'status':'cancelled' if e['status']=='cancelled' else 'confirmed',
            # A count-mode booking is a place for the day, not a time: keep it free in free/busy.
            'transparency':'transparent' if e['status']=='cancelled' or e.get('mode')=='count' else 'opaque',
            'start':{'dateTime':e['start']}, 'end':{'dateTime':e['end']},
            'extendedProperties':{'private':private}
        }
    def get(self,ident):
        from googleapiclient.errors import HttpError
        try:return self.decode(self.api.events().get(calendarId=self.calendar_id,eventId=ident).execute())
        except HttpError as e:
            if e.resp.status in (404,410):return None
            raise
    def insert(self,e):
        from googleapiclient.errors import HttpError
        try:self.api.events().insert(calendarId=self.calendar_id,body=self.encode(e)).execute(num_retries=0)
        except HttpError as err:
            if err.resp.status==409:
                found=self.get(e['id'])
                if found and all(found.get(k)==e.get(k) for k in ('owner','clinic','start','end','status')):return
                raise Conflict('Calendar ID collision')
            if err.resp.status>=500:raise Uncertain('Calendar insert outcome unknown') from None
            raise
        except (TimeoutError,OSError):raise Uncertain('Calendar insert outcome unknown') from None
    def update(self,e,etag=None):
        from googleapiclient.errors import HttpError
        body=self.encode(e);body.pop('id',None);body.pop('summary',None)
        # Patch preserves external doctor's descriptions, attendees, and other fields.
        req=self.api.events().patch(calendarId=self.calendar_id,eventId=e['id'],body=body)
        if etag:req.headers['If-Match']=etag
        try:req.execute(num_retries=0)
        except HttpError as err:
            if err.resp.status==412:raise Conflict('Event changed externally; review and reconfirm') from None
            if err.resp.status>=500:raise Uncertain('Calendar update outcome unknown') from None
            raise
        except (TimeoutError,OSError):raise Uncertain('Calendar update outcome unknown') from None
    def listing(self,**kwargs):
        out=[];token=None
        while True:
            result=self.api.events().list(calendarId=self.calendar_id,pageToken=token,maxResults=2500,**kwargs).execute()
            for raw in result.get('items',[]):
                e=self.decode(raw)
                # All-day intervals use the event's Calendar timezone, including DST.
                if raw.get('start',{}).get('date'):
                    from zoneinfo import ZoneInfo
                    tz=ZoneInfo(result.get('timeZone','UTC'))
                    for k in ('start','end'):e[k]=datetime.fromisoformat(raw[k]['date']).replace(tzinfo=tz).isoformat()
                out.append(e)
            token=result.get('nextPageToken')
            if not token:return out
    @staticmethod
    def patient_scope(clinic,owner):
        return hashlib.sha256(json.dumps([clinic,owner],separators=(',',':')).encode()).hexdigest()
    def owned_events(self,clinic,owner):
        # Repeated privateExtendedProperty constraints are OR, not AND.
        # One composite scope enforces both at Google's server before retrieval.
        return [e for e in self.listing(privateExtendedProperty=['patientScope='+self.patient_scope(clinic,owner)],singleEvents=True,showDeleted=True) if e.get('clinic')==clinic and e.get('owner')==owner and 'start' in e]
    def hide_cancelled(self,clinic):
        """Remove cancelled clinic events left visible by older versions. Returns the count."""
        stale=[e for e in self.listing(privateExtendedProperty=['clinicStatus=cancelled'],singleEvents=True,showDeleted=False) if e.get('clinic')==clinic]
        for e in stale:self.api.events().patch(calendarId=self.calendar_id,eventId=e['id'],body={'status':'cancelled'}).execute(num_retries=0)
        return len(stale)
    def managed_events(self,clinic):return self.listing(privateExtendedProperty=['clinic='+clinic],singleEvents=True,showDeleted=True)
    def schedule(self,a,b):return [e for e in self.listing(timeMin=a.isoformat(),timeMax=b.isoformat(),singleEvents=True,showDeleted=False) if e.get('status')!='cancelled' and 'start' in e and 'end' in e]
    def busy(self,a,b,exclude=None):
        # Freebusy never exposes event details to patient operations. It cannot
        # safely subtract an owned event from merged busy intervals; conservatively
        # reject reschedules that overlap the original live interval.
        result=self.api.freebusy().query(body={'timeMin':a.isoformat(),'timeMax':b.isoformat(),'items':[{'id':self.calendar_id}]}).execute()
        cal=result['calendars'][self.calendar_id]
        if cal.get('errors'):raise RuntimeError('Calendar availability unavailable')
        return [(x['start'],x['end']) for x in cal['busy']]
    def review_conflicts(self):
        now=datetime.now().astimezone();events=[e for e in self.schedule(now,now+timedelta(days=30)) if e.get('mode')!='count'];pairs=[]
        for i,e in enumerate(events):
            for f in events[i+1:]:
                if stamp(e['start'])<stamp(f['end']) and stamp(f['start'])<stamp(e['end']):pairs.append([e['id'],f['id']])
        return pairs

class Sheets:
    HEADERS=['Appointment ID','Start','End','Status','Kind','Last Seen','Issue']
    def __init__(self,creds,ident):
        from googleapiclient.discovery import build
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{10,200}',ident or ''):raise ValueError('Valid configured spreadsheet ID required')
        self.api=build('sheets','v4',credentials=creds,cache_discovery=False);self.ident=ident
    @classmethod
    def create(cls,creds,title):
        """Setup-only creation after the human chooses a new register."""
        from googleapiclient.discovery import build
        if not isinstance(title,str) or not title.strip() or len(title)>200:raise ValueError('Provide a register title of 1–200 characters')
        api=build('sheets','v4',credentials=creds,cache_discovery=False)
        created=api.spreadsheets().create(body={'properties':{'title':title.strip()},'sheets':[
            {'properties':{'title':'Appointments'}},{'properties':{'title':'Daily Summary'}}]},fields='spreadsheetId').execute(num_retries=0)
        # A timed-out create must be reviewed by the human, never blindly retried.
        result=cls(creds,created['spreadsheetId']);result.initialize_register();return result
    def initialize_register(self):
        """Preflight existing owned tabs; preserve data and unrelated worksheets."""
        meta=self.verify();titles={x['properties']['title'] for x in meta['sheets']}
        headers={'Appointments':self.HEADERS,'Daily Summary':['Date','Status','Appointments']}
        empty=[]
        for title,expected in headers.items():
            if title not in titles:empty.append(title);continue
            if title=='Appointments':self.read_records() # schema + duplicate IDs
            rows=self.api.spreadsheets().values().get(spreadsheetId=self.ident,range="'"+title+"'!"+('A:G' if title=='Appointments' else 'A:C')).execute().get('values',[])
            if rows and rows[0]!=expected:raise ValueError(title+' schema mismatch; refusing overwrite')
            if not rows:empty.append(title)
        self.ensure()
        if empty:self.api.spreadsheets().values().batchUpdate(spreadsheetId=self.ident,body={'valueInputOption':'RAW','data':[
            {'range':"'"+title+"'!A1",'values':[headers[title]]} for title in empty]}).execute(num_retries=0)
        return {'initialized':True,'worksheets':['Appointments','Daily Summary']}
    def verify(self):return self.api.spreadsheets().get(spreadsheetId=self.ident,fields='spreadsheetId,properties.title,sheets.properties').execute()
    def ensure(self):
        meta=self.verify();titles={s['properties']['title'] for s in meta['sheets']}
        missing=[x for x in ('Appointments','Daily Summary') if x not in titles]
        if missing:self.api.spreadsheets().batchUpdate(spreadsheetId=self.ident,body={'requests':[{'addSheet':{'properties':{'title':x}}} for x in missing]}).execute()
    def read_records(self):
        meta=self.verify()
        if 'Appointments' not in {s['properties']['title'] for s in meta['sheets']}:return {}
        values=self.api.spreadsheets().values().get(spreadsheetId=self.ident,range="'Appointments'!A:G").execute().get('values',[])
        if values and values[0]!=self.HEADERS:raise ValueError('Appointments schema mismatch; refusing overwrite')
        records={}
        for row in values[1:]:
            row=row+['']*(7-len(row))
            if row[0] in records:raise ValueError('Duplicate register IDs require doctor review')
            if row[0]:records[row[0]]=dict(zip(('id','start','end','status','kind','last_seen','issue'),row))
        return records
    def write_records(self,records):
        self.ensure()
        rows=[self.HEADERS]+[[e.get(k,'') for k in ('id','start','end','status','kind','last_seen','issue')] for _,e in sorted(records.items())]
        daily={}
        for e in records.values():
            key=(e.get('start','')[:10],e.get('status','unknown'));daily[key]=daily.get(key,0)+1
        summary=[['Date','Status','Appointments']]+[[d,s,n] for (d,s),n in sorted(daily.items())]
        # Deterministic overwrite, never append. All historical rows retained.
        self.api.spreadsheets().values().batchUpdate(spreadsheetId=self.ident,body={'valueInputOption':'RAW','data':[{'range':"'Appointments'!A1",'values':rows},{'range':"'Daily Summary'!A1",'values':summary}]}).execute(num_retries=0)
        # Remove stale summary tails without clearing appointment history.
        self.api.spreadsheets().values().clear(spreadsheetId=self.ident,range=f"'Daily Summary'!A{len(summary)+1}:C").execute()
    def status(self):
        r=self.read_records();return {'rows':len(r),'issues':[{'id':k,'issue':v['issue']} for k,v in r.items() if v.get('issue')],'last_seen':max((v.get('last_seen','') for v in r.values()),default=None)}
    def open(self):
        self.verify();return {'opened':webbrowser.open('https://docs.google.com/spreadsheets/d/'+self.ident+'/edit')}
