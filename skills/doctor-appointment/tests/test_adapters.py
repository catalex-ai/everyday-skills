"""API-boundary tests use fake transports; no Google or model connection."""
import unittest,sys,copy,json,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from google_adapter import Calendar,Sheets,keychain,connect,SCOPES
from core import DEFAULT,Service,Identity,Conflict
from mock import MockCalendar,MockSheets,fixture
from verification import verify_google

class Request:
    def __init__(self,value=None,error=None):self.value=value;self.error=error;self.headers={};self.retries=None
    def execute(self,**kwargs):
        self.retries=kwargs
        if self.error:raise self.error
        return self.value

class GoogleBoundaryTests(unittest.TestCase):
    def test_listing_pagination_all_day_timezone(self):
        class API:
            def __init__(self):self.calls=[]
            def events(self):return self
            def list(self,**kw):
                self.calls.append(kw)
                if kw['pageToken'] is None:return Request({'items':[{'id':'day','start':{'date':'2027-03-14'},'end':{'date':'2027-03-15'}}],'timeZone':'America/New_York','nextPageToken':'p2'})
                return Request({'items':[]})
        c=object.__new__(Calendar);c.api=API();c.calendar_id='explicit-id';out=c.listing()
        self.assertEqual(len(c.api.calls),2);self.assertTrue(out[0]['start'].endswith('-05:00'));self.assertTrue(out[0]['end'].endswith('-04:00'))
    def test_patient_availability_uses_only_freebusy(self):
        class API:
            def freebusy(self):return self
            def query(self,body):return Request({'calendars':{'explicit':{'busy':[{'start':'2027-01-01T10:00:00Z','end':'2027-01-01T11:00:00Z'}]}}})
            def events(self):raise AssertionError('Patient full calendar fetch')
        from core import stamp
        c=object.__new__(Calendar);c.api=API();c.calendar_id='explicit'
        for excluded in (None,'owned-id'):
            self.assertEqual(len(c.busy(stamp('2027-01-01T00:00:00Z'),stamp('2027-01-02T00:00:00Z'),excluded)),1)
    def test_freebusy_api_error_fails_closed(self):
        class API:
            def freebusy(self):return self
            def query(self,**kw):return Request({'calendars':{'explicit':{'errors':[{'reason':'notFound'}]}}})
        from core import stamp
        c=object.__new__(Calendar);c.api=API();c.calendar_id='explicit'
        with self.assertRaises(RuntimeError):c.busy(stamp('2027-01-01T00:00:00Z'),stamp('2027-01-02T00:00:00Z'))
    def test_scope_is_single_composite_value(self):
        c=object.__new__(Calendar);calls=[]
        c.listing=lambda **kw:calls.append(kw) or [{'id':'wrong','clinic':'c','owner':'b','start':'x'},{'id':'right','clinic':'c','owner':'a','start':'x'}]
        out=c.owned_events('c','a');self.assertEqual([e['id'] for e in out],['right'])
        self.assertEqual(len(calls[0]['privateExtendedProperty']),1)
        self.assertNotEqual(Calendar.patient_scope('c','a'),Calendar.patient_scope('c','b'))
    def test_etag_conflict_preserves_external_changes(self):
        from googleapiclient.errors import HttpError
        from httplib2 import Response
        req=Request(error=HttpError(Response({'status':'412'}),b'changed'))
        class API:
            def events(self):return self
            def patch(self,**kw):self.body=kw['body'];return req
        c=object.__new__(Calendar);c.api=API();c.calendar_id='explicit';e=next(iter(fixture()['events'].values()))
        with self.assertRaises(Conflict):c.update(e,'etag-current')
        self.assertEqual(req.headers['If-Match'],'etag-current');self.assertNotIn('summary',c.api.body);self.assertNotIn('description',c.api.body)
    def test_cancellation_removes_event_from_calendar_view(self):
        # A cancelled appointment must not stay visible on the doctor's calendar,
        # or it looks booked while availability (correctly) offers that slot.
        req=Request()
        class API:
            def events(self):return self
            def patch(self,**kw):self.body=kw['body'];return req
        c=object.__new__(Calendar);c.api=API();c.calendar_id='explicit'
        e=dict(next(iter(fixture()['events'].values())),status='cancelled')
        c.update(e,'etag')
        self.assertEqual(c.api.body['status'],'cancelled')
        self.assertEqual(c.api.body['extendedProperties']['private']['clinicStatus'],'cancelled')
        self.assertEqual(Calendar.encode(dict(e,status='confirmed'))['status'],'confirmed')
    def test_count_booking_round_trips_and_stays_free_in_google(self):
        # Free/busy must ignore a day place, or one count booking blocks the whole day.
        e=dict(next(iter(fixture()['events'].values())),mode='count',category='follow_up')
        raw=Calendar.encode(e)
        self.assertEqual(raw['transparency'],'transparent')
        back=Calendar.decode(raw)
        self.assertEqual((back['mode'],back['category']),('count','follow_up'))
        self.assertEqual(Calendar.encode(dict(e,mode=None,category=None))['transparency'],'opaque')
    def test_google_conflict_review_ignores_count_bookings(self):
        e=next(iter(fixture()['events'].values()))
        same_day=[dict(e,id='one',mode='count'),dict(e,id='two',mode='count')]
        c=object.__new__(Calendar);c.schedule=lambda a,b:same_day
        self.assertEqual(c.review_conflicts(),[])
    def test_cancel_and_sync_accept_cancelled_event_without_times(self):
        from core import Service,Identity,DEFAULT
        state=fixture();cal=MockCalendar(state['events']);sheets=MockSheets()
        real_get=cal.get
        def bare(ident):
            e=real_get(ident)
            return {k:v for k,v in e.items() if k not in ('start','end')} if e and e['status']=='cancelled' else e
        cal.get=bare;managed=cal.managed_events
        cal.managed_events=lambda clinic:[{k:v for k,v in e.items() if e['status']!='cancelled' or k not in ('start','end')} for e in managed(clinic)]
        doctor=Service(Identity('d','doctor',DEFAULT['clinic_id'],'synthetic',True),cal,sheets)
        args={'appointment_id':'a-demo'};d=doctor.call('doctor_cancel_appointment',args)
        self.assertTrue(doctor.call('doctor_cancel_appointment',args|{'confirmation_token':d['confirmation_token']})['calendar_confirmed'])
        doctor.call('doctor_sync_register',{})
        self.assertTrue(doctor.call('doctor_sync_register',{})['synced']);self.assertEqual(sheets.records['a-demo']['status'],'cancelled')
    def test_agreed_time_survives_google_round_trip(self):
        e=dict(next(e for e in fixture()['events'].values() if e['kind']=='appointment'),agreed='a|b|confirmed')
        raw=Calendar.encode(e);raw['status']='cancelled'  # deleted directly in Google Calendar
        back=Calendar.decode(raw)
        self.assertEqual(back['agreed'],'a|b|confirmed');self.assertEqual(back['status'],'cancelled');self.assertEqual(back['clinic_status'],'confirmed')
    def test_oauth_missing_installed_client(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'client.json';p.write_text(json.dumps({'web':{}}))
            with patch('google_adapter.keychain',return_value=object()):
                with self.assertRaises(ValueError):connect(p,'explicit','real-spreadsheet-id')
    def test_secure_storage_unavailable_stops(self):
        with patch('keyring.get_keyring',return_value=object()):
            with self.assertRaises(RuntimeError):keychain()
    def test_no_credential_retrieval_tool(self):
        from core import PATIENT,DOCTOR,ARGUMENTS
        for name in PATIENT|DOCTOR:
            self.assertNotIn('credential',name);self.assertNotIn('token',ARGUMENTS[name]['properties'])
    def test_cancelled_google_tombstone_not_reactivated(self):
        raw={'id':'x','status':'cancelled','extendedProperties':{'private':{'clinicStatus':'confirmed'}}}
        self.assertEqual(Calendar.decode(raw)['status'],'cancelled')
    def test_sheets_reject_duplicate_ids_and_schema(self):
        class API:
            def __init__(self,rows):self.rows=rows
            def spreadsheets(self):return self
            def values(self):return self
            def get(self,**kw):return Request({'values':self.rows})
        for rows in ([['wrong']], [Sheets.HEADERS,['x'],['x']]):
            s=object.__new__(Sheets);s.ident='explicit';s.api=API(rows);s.verify=lambda:{'sheets':[{'properties':{'title':'Appointments'}}]}
            with self.assertRaises(ValueError):s.read_records()
    def test_sheets_write_is_raw_overwrite_not_append(self):
        class API:
            def __init__(self):self.writes=[]
            def spreadsheets(self):return self
            def values(self):return self
            def batchUpdate(self,**kw):self.writes.append(kw);return Request({})
            def clear(self,**kw):return Request({})
        s=object.__new__(Sheets);s.ident='explicit';s.api=API();s.ensure=lambda:None
        rows={'stable':{'id':'stable','start':'2027-01-01T10:00:00Z','status':'confirmed'}}
        s.write_records(rows);s.write_records(rows)
        self.assertEqual(s.api.writes[0],s.api.writes[1]);self.assertEqual(s.api.writes[0]['body']['valueInputOption'],'RAW')
    def test_staged_google_workflow_with_mock_transports(self):
        state=fixture();c=MockCalendar(state['events']);s=MockSheets();day=state['events']['a-demo']['start'][:10]
        approvals=[]
        out=verify_google(c,s,DEFAULT,day+'T14:00:00+05:30',lambda action,payload:approvals.append(action) or True,log=lambda m:None)
        self.assertTrue(out['passed'],out);self.assertEqual(approvals,['book','cancel'])
        self.assertEqual(out['duplicate_prevention']['calendar_events_for_owner'],1);self.assertEqual(out['duplicate_prevention']['register_id_count'],1)
        self.assertEqual(s.records[out['id']]['status'],'cancelled')
    def test_staged_google_refusal_does_not_write(self):
        state=fixture();c=MockCalendar(state['events']);s=MockSheets();day=state['events']['a-demo']['start'][:10]
        from core import Denied
        with self.assertRaises(Denied):verify_google(c,s,DEFAULT,day+'T14:00:00+05:30',lambda action,payload:False,log=lambda m:None)
        self.assertEqual(c.events,state['events']);self.assertEqual(s.records,{})

if __name__=='__main__':unittest.main()
