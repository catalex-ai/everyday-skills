"""Mock-only operator OAuth setup checks. No Google account or network is used."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
import types
import contextlib
from pathlib import Path
from unittest.mock import patch, Mock

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import admin
import google_adapter


class OAuthSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'package'
        self.root.mkdir()
        self.outside = Path(self.tmp.name) / 'desktop-client.json'
        self.outside.write_text(json.dumps({'installed': {'client_id': 'mock-client'}}))
        self.config = self.root / 'config' / 'google-clinic.json'
        self.patches = [patch.object(admin, 'ROOT', self.root)]
        for p in self.patches: p.start()
        self.creds=object()
        self.events=[]
        self.real_authorize=google_adapter.authorize
        self.calendar_choices=[{'id':'clinic-calendar-id','summary':'Clinic Schedule','accessRole':'writer'}]

        class FakeCalendar:
            def __init__(_, creds, ident): self.events.append(('calendar',ident))
            def verify(_): self.events.append(('calendar-verified',))
        class FakeSheets:
            def __init__(_, creds, ident): _.ident=ident;self.events.append(('existing-sheet',ident))
            @classmethod
            def create(_, creds, title):
                self.events.append(('create',title));result=FakeSheets(creds,'created-register-id_123');result.initialize_register();return result
            def initialize_register(_): self.events.append(('initialize',_.ident))
            def verify(_): self.events.append(('sheet-verified',_.ident))
        self.FakeSheets=FakeSheets
        self.patches += [
            patch.object(google_adapter,'authorize',side_effect=lambda path:self.events.append(('authorize',path)) or self.creds,create=True),
            patch.object(google_adapter,'list_calendars',side_effect=lambda creds:self.events.append(('list-calendars',)) or self.calendar_choices,create=True),
            patch.object(google_adapter,'store_credentials',side_effect=lambda creds:self.events.append(('store',)),create=True),
            patch.object(google_adapter,'Calendar',FakeCalendar),patch.object(google_adapter,'Sheets',FakeSheets),
        ]
        for p in self.patches[1:]: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def run_setup(self, answers=(), args=()):
        with patch.object(sys, 'argv', ['admin.py', 'google-setup', *args]), patch('builtins.input', side_effect=answers):
            admin.main()

    def invoke(self, answers=(), args=()):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.run_setup(answers,args)
        return output.getvalue()

    def test_create_choice_triggers_one_oauth_and_persists_selected_calendar_and_new_sheet(self):
        out=self.invoke(['1','New clinic register','1'],['--client',str(self.outside)])
        self.assertEqual(sum(e[0]=='authorize' for e in self.events),1)
        self.assertIn(('create','New clinic register'),self.events)
        self.assertEqual(self.events.count(('initialize','created-register-id_123')),1)
        self.assertIn(('calendar','clinic-calendar-id'),self.events)
        self.assertIn(('calendar-verified',),self.events)
        self.assertLess(self.events.index(('sheet-verified','created-register-id_123')),self.events.index(('store',)))
        saved=json.loads(self.config.read_text())
        self.assertEqual((saved['calendar_id'],saved['spreadsheet_id']),('clinic-calendar-id','created-register-id_123'))
        self.assertIn('https://docs.google.com/spreadsheets/d/created-register-id_123/edit',out)

    def test_existing_sheet_url_initializes_but_never_creates(self):
        out=self.invoke(['2','https://docs.google.com/spreadsheets/d/existing_sheet-id_123/edit?gid=0','1'],['--client',str(self.outside)])
        self.assertFalse(any(e[0]=='create' for e in self.events))
        self.assertIn(('existing-sheet','existing_sheet-id_123'),self.events)
        self.assertIn(('initialize','existing_sheet-id_123'),self.events)
        self.assertIn('Clinic Schedule',out)
        self.assertEqual(json.loads(self.config.read_text())['spreadsheet_id'],'existing_sheet-id_123')

    def test_invalid_spreadsheet_urls_fail_before_oauth(self):
        for url in ('http://docs.google.com/spreadsheets/d/abcdefghij/edit','https://evil.example/spreadsheets/d/abcdefghij/edit','https://docs.google.com/spreadsheets/d/short/edit'):
            self.events.clear()
            with patch.object(sys,'argv',['admin.py','google-setup','--client',str(self.outside)]),patch('builtins.input',side_effect=['2',url]),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):admin.run()
            self.assertFalse(any(e[0]=='authorize' for e in self.events))

    def test_missing_client_fails_before_oauth(self):
        with patch.object(sys,'argv',['admin.py','google-setup','--client',str(Path(self.tmp.name)/'missing.json')]),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):admin.run()
        self.assertFalse(any(e[0]=='authorize' for e in self.events))

    def test_package_client_path_rejected_before_oauth(self):
        inside=self.root/'client.json';inside.write_text('{}')
        with patch.object(sys,'argv',['admin.py','google-setup','--client',str(inside)]),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):admin.run()
        self.assertFalse(any(e[0]=='authorize' for e in self.events))

    def test_explicit_literal_primary_is_rejected_and_actual_calendar_id_is_saved(self):
        with patch.object(sys,'argv',['admin.py','google-setup','--client',str(self.outside),'--calendar-id','primary']),patch('builtins.input',side_effect=['2','https://docs.google.com/spreadsheets/d/existing_sheet-id_123/edit']),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):admin.run()
        self.assertFalse(any(e[0]=='existing-sheet' for e in self.events))
        self.events.clear()
        self.invoke(['2','https://docs.google.com/spreadsheets/d/existing_sheet-id_123/edit','1'],['--client',str(self.outside)])
        self.assertEqual(json.loads(self.config.read_text())['calendar_id'],'clinic-calendar-id')

    def test_credentials_stored_only_after_both_resource_verifications(self):
        self.invoke(['2','https://docs.google.com/spreadsheets/d/existing_sheet-id_123/edit','1'],['--client',str(self.outside)])
        self.assertLess(self.events.index(('calendar-verified',)),self.events.index(('store',)))
        self.assertLess(self.events.index(('sheet-verified','existing_sheet-id_123')),self.events.index(('store',)))

    def test_oauth_exception_output_is_redacted(self):
        marker='MOCK_CREDENTIAL_VALUE'
        with patch.object(google_adapter,'authorize',side_effect=RuntimeError(marker)),patch.object(sys,'argv',['admin.py','google-setup','--client',str(self.outside)]),patch('builtins.input',side_effect=['2','https://docs.google.com/spreadsheets/d/existing_sheet-id_123/edit']),contextlib.redirect_stderr(io.StringIO()) as err,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):admin.run()
        self.assertNotIn(marker,err.getvalue())

    def flow_module(self,flow_class):
        package=types.ModuleType('google_auth_oauthlib');package.__path__=[]
        module=types.ModuleType('google_auth_oauthlib.flow');module.InstalledAppFlow=flow_class
        return {'google_auth_oauthlib':package,'google_auth_oauthlib.flow':module}

    def test_real_authorize_helper_uses_loopback_browser_and_offline_consent(self):
        events=[]
        class Creds:
            refresh_token='mock-refresh-token'
        class Flow:
            @classmethod
            def from_client_config(cls,client,scopes):events.append(('client',client,scopes));return cls()
            def run_local_server(self,**kwargs):events.append(('browser',kwargs));return Creds()
        with patch.dict(sys.modules,self.flow_module(Flow)),patch.object(google_adapter,'authorize',self.real_authorize),patch.object(google_adapter,'keychain',side_effect=lambda:events.append(('keychain',)) or object()):
            creds=google_adapter.authorize(self.outside)
        self.assertEqual(creds.refresh_token,'mock-refresh-token')
        self.assertLess(events.index(('keychain',)),next(i for i,e in enumerate(events) if e[0]=='browser'))
        opts=next(e[1] for e in events if e[0]=='browser')
        self.assertEqual((opts['host'],opts['port'],opts['open_browser']),('127.0.0.1',0,True))
        self.assertEqual((opts['access_type'],opts['prompt']),('offline','consent'))

    def test_authorize_denies_wrong_client_and_missing_refresh_token(self):
        flow=types.SimpleNamespace(from_client_config=Mock())
        with patch.dict(sys.modules,self.flow_module(flow)),patch.object(google_adapter,'authorize',self.real_authorize),patch.object(google_adapter,'keychain',return_value=object()):
            wrong=self.root.parent/'web-client.json';wrong.write_text(json.dumps({'web':{'client_id':'mock'}}))
            with self.assertRaisesRegex(ValueError,'Desktop app client'):
                google_adapter.authorize(wrong)
        flow.from_client_config.assert_not_called()
        class NoRefresh:
            refresh_token=None
        class Flow:
            @classmethod
            def from_client_config(cls,*args):return cls()
            def run_local_server(self,**kwargs):return NoRefresh()
        with patch.dict(sys.modules,self.flow_module(Flow)),patch.object(google_adapter,'authorize',self.real_authorize),patch.object(google_adapter,'keychain',return_value=object()):
            with self.assertRaisesRegex(RuntimeError,'No refresh token'):
                google_adapter.authorize(self.outside)

    def test_secure_storage_failure_prevents_flow_and_browser(self):
        flow=types.SimpleNamespace(from_client_config=Mock())
        with patch.dict(sys.modules,self.flow_module(flow)),patch.object(google_adapter,'authorize',self.real_authorize),patch.object(google_adapter,'keychain',side_effect=RuntimeError('secure store unavailable')):
            with self.assertRaisesRegex(RuntimeError,'secure store unavailable'):
                google_adapter.authorize(self.outside)
        flow.from_client_config.assert_not_called()

    def test_legacy_connect_verifies_both_resources_before_storage(self):
        events=[];creds=object()
        with patch.object(google_adapter,'authorize',side_effect=lambda path:events.append(('authorize',path)) or creds),\
             patch.object(google_adapter,'Calendar') as calendar,patch.object(google_adapter,'Sheets') as sheets,\
             patch.object(google_adapter,'store_credentials',side_effect=lambda c:events.append(('store',))):
            calendar.return_value.verify.side_effect=lambda:events.append(('calendar-verified',))
            sheets.return_value.verify.side_effect=lambda:events.append(('sheets-verified',))
            result=google_adapter.connect(self.outside,'calendar-id','spreadsheet-id_123')
        self.assertTrue(result['connected'])
        self.assertLess(events.index(('calendar-verified',)),events.index(('store',)))
        self.assertLess(events.index(('sheets-verified',)),events.index(('store',)))


class SheetsSetupApiTests(unittest.TestCase):
    class Request:
        def __init__(self,value=None):self.value=value
        def execute(self,**kwargs):return self.value

    class NewRegisterApi:
        def __init__(self):self.create_call=None;self.writes=[]
        def spreadsheets(self):return self
        def create(self,**kwargs):
            self.create_call=kwargs
            return SheetsSetupApiTests.Request({'spreadsheetId':'google-returned-register-id'})
        def values(self):return self
        def get(self,**kwargs):
            if 'fields' in kwargs:return SheetsSetupApiTests.Request({'spreadsheetId':'google-returned-register-id','sheets':[{'properties':{'title':'Appointments'}},{'properties':{'title':'Daily Summary'}}]})
            return SheetsSetupApiTests.Request({'values':[]})
        def batchUpdate(self,**kwargs):self.writes.append(kwargs);return SheetsSetupApiTests.Request({})

    class ExistingRegisterApi:
        def __init__(self,appointment_header=None,daily_header=None):
            self.appointment_header=appointment_header or google_adapter.Sheets.HEADERS
            self.daily_header=daily_header or ['Date','Status','Appointments']
            self.mutations=[];self.read_ranges=[]
        def spreadsheets(self):return self
        def values(self):return self
        def get(self,**kwargs):
            if 'fields' in kwargs:
                return SheetsSetupApiTests.Request({'spreadsheetId':'existing-register-id','sheets':[{'properties':{'title':'Appointments'}},{'properties':{'title':'Daily Summary'}},{'properties':{'title':'Doctor Notes'}}]})
            target=kwargs['range'];self.read_ranges.append(target)
            if 'Appointments' in target:return SheetsSetupApiTests.Request({'values':[self.appointment_header,['kept-row','2027-01-02','2027-01-02','confirmed','appointment','yesterday','']]})
            if 'Daily Summary' in target:return SheetsSetupApiTests.Request({'values':[self.daily_header,['2027-01-02','confirmed','1']]})
            raise AssertionError('Unexpected worksheet read')
        def batchUpdate(self,**kwargs):self.mutations.append(('batch',kwargs));return SheetsSetupApiTests.Request({})
        def clear(self,**kwargs):self.mutations.append(('clear',kwargs));return SheetsSetupApiTests.Request({})

    @staticmethod
    def build_modules(build):
        root=types.ModuleType('googleapiclient');root.__path__=[]
        discovery=types.ModuleType('googleapiclient.discovery');discovery.build=build
        return {'googleapiclient':root,'googleapiclient.discovery':discovery}

    def test_create_uses_title_returns_google_id_and_writes_only_raw_owned_headers(self):
        created=self.NewRegisterApi();register=self.ExistingRegisterApi(appointment_header=[],daily_header=[])
        # Freshly created resource has both tabs and no cells; use its API shape
        # with the verify response and empty owned ranges.
        register=types.SimpleNamespace()
        register.spreadsheets=lambda:register
        register.create=None
        register.get=lambda **kw:self.Request({'spreadsheetId':'google-returned-register-id','sheets':[{'properties':{'title':'Appointments'}},{'properties':{'title':'Daily Summary'}}]}) if 'fields' in kw else self.Request({'values':[]})
        register.values=lambda:register
        register.batchUpdate=lambda **kw:created.writes.append(kw) or self.Request({})
        build=Mock(side_effect=[created,register])
        with patch.dict(sys.modules,self.build_modules(build)):
            result=google_adapter.Sheets.create(object(),'  Front Desk Register  ')
        self.assertEqual(result.ident,'google-returned-register-id')
        self.assertEqual(created.create_call['body']['properties']['title'],'Front Desk Register')
        self.assertEqual(created.create_call['fields'],'spreadsheetId')
        self.assertEqual([x['properties']['title'] for x in created.create_call['body']['sheets']],['Appointments','Daily Summary'])
        write=created.writes[0]
        self.assertEqual(write['body']['valueInputOption'],'RAW')
        self.assertEqual([row['range'] for row in write['body']['data']], ["'Appointments'!A1","'Daily Summary'!A1"])
        self.assertEqual(write['body']['data'][0]['values'][0],google_adapter.Sheets.HEADERS)
        self.assertEqual(write['body']['data'][1]['values'][0],['Date','Status','Appointments'])

    def test_existing_register_preserves_records_and_unrelated_worksheets_and_init_is_idempotent(self):
        api=self.ExistingRegisterApi()
        with patch.dict(sys.modules,self.build_modules(lambda *args,**kwargs:api)):
            sheets=google_adapter.Sheets(object(),'existing-register-id')
            self.assertTrue(sheets.initialize_register()['initialized'])
            self.assertTrue(sheets.initialize_register()['initialized'])
        self.assertEqual(api.mutations,[])
        self.assertTrue(any('Appointments' in r for r in api.read_ranges))
        self.assertTrue(any('Daily Summary' in r for r in api.read_ranges))
        self.assertFalse(any('Doctor Notes' in r for r in api.read_ranges))

    def test_mismatched_owned_sheet_schemas_abort_before_any_mutation(self):
        for api in (self.ExistingRegisterApi(appointment_header=['Wrong']),self.ExistingRegisterApi(daily_header=['Wrong'])):
            with self.subTest(header=api.appointment_header if api.appointment_header!=google_adapter.Sheets.HEADERS else api.daily_header),patch.dict(sys.modules,self.build_modules(lambda *args,**kwargs:api)):
                sheets=google_adapter.Sheets(object(),'existing-register-id')
                with self.assertRaises(ValueError):sheets.initialize_register()
                self.assertEqual(api.mutations,[])

    def test_google_scopes_do_not_include_broad_drive_access(self):
        self.assertEqual(set(google_adapter.SCOPES),{
            'https://www.googleapis.com/auth/calendar.events',
            'https://www.googleapis.com/auth/calendar.readonly',
            'https://www.googleapis.com/auth/spreadsheets'})


if __name__ == '__main__': unittest.main()
