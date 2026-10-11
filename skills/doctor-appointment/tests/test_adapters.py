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
        answers=iter([day+'T14:00:00+05:30','CREATE SYNTHETIC TEST','ROW VERIFIED','CANCEL SYNTHETIC TEST'])
        with patch('audit.audit',return_value={'sessions':'mocked','real_patient_enabled':False}):
            out=verify_google(c,s,DEFAULT,lambda text:next(answers))
        for k in ('calendar_verified','row_human_verified','no_duplicate_verified','cancellation_sync_verified','patient_isolation_verified'):self.assertTrue(out[k])
        self.assertEqual(s.records[out['id']]['status'],'cancelled')
    def test_staged_google_refusal_does_not_write(self):
        state=fixture();c=MockCalendar(state['events']);s=MockSheets();day=state['events']['a-demo']['start'][:10]
        answers=iter([day+'T14:00:00+05:30','NO'])
        self.assertTrue(verify_google(c,s,DEFAULT,lambda text:next(answers))['aborted']);self.assertEqual(c.events,state['events']);self.assertEqual(s.records,{})

if __name__=='__main__':unittest.main()
