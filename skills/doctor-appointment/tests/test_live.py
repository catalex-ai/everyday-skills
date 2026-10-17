"""Live-mode gating, approver and fail-closed tests; no Google or model calls."""
import unittest,sys,json,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import live,server
from core import DEFAULT,Service,Identity,Denied,ARGUMENTS
from mock import MockCalendar,MockSheets,fixture,free_demo_day

class LiveGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();d=Path(self.tmp.name)
        self.cfg=d/'google-clinic.json';self.act=d/'live-activation.json'
        self.cfg.write_text(json.dumps(DEFAULT|{'calendar_id':'clinic-cal','spreadsheet_id':'sheet_id_12345'}))
        self.storage=d/'storage.json';self.local=d/'local-bookings.json'
        self.patches=[patch.object(live,'CONFIG',self.cfg),patch.object(live,'ACTIVATION',self.act),patch.object(live,'STORAGE',self.storage),patch.object(server,'LOCAL_STATE',self.local)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.tmp.cleanup()
    def activate(self,**over):
        c=json.loads(self.cfg.read_text())
        self.act.write_text(json.dumps({'resources':live.resources(c),'real_patient_enabled':False}|over))
    def test_without_activation_practice_runtime_is_explicit(self):
        self.cfg.unlink()
        self.assertFalse(live.live_state()['required'])
        self.assertIsInstance(server.make_runtime('patient','patient-a'),server.PracticeRuntime)
    def test_valid_activation_is_active(self):
        self.activate();self.assertTrue(live.live_state()['active'])
    def test_code_update_keeps_google_mode(self):
        # Activation binds to the chosen resources only, so updating the package never drops Google.
        self.activate();(Path(self.tmp.name)/'unrelated.py').write_text('x=1')
        self.assertTrue(live.live_state()['active'])
    def test_resource_change_fails_closed_without_local_fallback(self):
        self.activate();self.storage.write_text(json.dumps({'storage':'laptop'}))
        c=json.loads(self.cfg.read_text());c['calendar_id']='other-cal';self.cfg.write_text(json.dumps(c))
        self.assertFalse(live.live_state()['active'])
        rt=server.make_runtime('patient','patient-a');self.assertIsInstance(rt,live.UnavailableRuntime)
        with self.assertRaises(PermissionError):rt.call('get_my_appointments',{})
    def test_real_patient_flag_in_activation_rejected(self):
        self.activate(real_patient_enabled=True);self.assertFalse(live.live_state()['active'])
    def test_invalid_credentials_fail_closed(self):
        self.activate()
        with patch.object(live,'google_clients',side_effect=RuntimeError('no keychain')):
            rt=server.make_runtime('doctor','patient-a')
        self.assertIsInstance(rt,live.UnavailableRuntime);self.assertIn('authorization',rt.reason)

    def test_malformed_activation_fails_closed(self):
        for content in ('{', '[]', 'null'):
            with self.subTest(content=content):
                self.act.write_text(content)
                self.assertTrue(live.live_state()['required'])
                self.assertFalse(live.live_state()['active'])
                self.assertIsInstance(server.make_runtime('patient','patient-a'),live.UnavailableRuntime)
    def test_unreadable_activation_fails_closed_without_exception_text(self):
        self.activate()
        with patch.object(live,'read_json',side_effect=PermissionError('secret-canary')):
            state=live.live_state()
        self.assertTrue(state['required']);self.assertFalse(state['active'])
        self.assertNotIn('secret-canary',state['reason'])
    def test_laptop_choice_uses_local_bookings_and_starts_empty(self):
        import admin
        with patch.object(admin,'ROOT',Path(self.tmp.name)):admin.use_laptop()
        self.assertEqual(live.storage_choice(),'laptop')
        rt=server.make_runtime('patient','patient-a');self.assertIsInstance(rt,server.LocalRuntime)
        with patch.object(server,'lock',lambda p:__import__('contextlib').nullcontext()):
            out=rt.call('get_my_appointments',{})
        self.assertEqual(out['appointments'],[]);self.assertFalse(out['google_accessed']);self.assertEqual(out['execution_mode'],'this-computer')
        self.assertFalse(json.loads(self.local.read_text())['fail_next'])
    def test_laptop_choice_never_resets_existing_bookings(self):
        import admin
        self.local.write_text(json.dumps({'config':DEFAULT,'events':{'kept':{}},'records':{},'fail_next':False,'last_sync':'never'}))
        with patch.object(admin,'ROOT',Path(self.tmp.name)):admin.use_laptop()
        self.assertIn('kept',json.loads(self.local.read_text())['events'])
    def test_laptop_choice_turns_google_off_and_activation_wins_over_laptop(self):
        import admin
        self.activate()
        with patch.object(admin,'ROOT',Path(self.tmp.name)):admin.use_laptop()
        self.assertFalse(self.act.exists());self.assertEqual(live.storage_choice(),'laptop')
        self.activate();self.assertEqual(live.storage_choice(),'google')
    def test_local_runtime_without_setup_refuses_instead_of_demo_data(self):
        self.storage.write_text(json.dumps({'storage':'laptop'}))
        rt=server.make_runtime('doctor','patient-a')
        with patch.object(server,'lock',lambda p:__import__('contextlib').nullcontext()):
            with self.assertRaises(PermissionError):rt.call('doctor_get_schedule',{'day':'2030-01-07'})
    def test_tool_descriptions_follow_effective_backend(self):
        self.cfg.unlink()
        practice=server.make_runtime('patient','patient-a')
        self.assertIn('Offline synthetic practice',server.tool_definitions(practice)[0]['description'])
        self.storage.write_text(json.dumps({'storage':'laptop'}))
        self.assertIn('kept on this computer',server.tool_definitions(server.make_runtime('patient','patient-a'))[0]['description'])
        self.storage.unlink()
        unavailable=live.UnavailableRuntime('patient','not ready')
        self.assertIn('unavailable',server.tool_definitions(unavailable)[0]['description'])
        self.cfg.write_text(json.dumps(DEFAULT|{'calendar_id':'clinic-cal','spreadsheet_id':'sheet_id_12345'}))
        self.activate()
        with patch.object(live,'google_clients',return_value=(None,MockCalendar(),MockSheets())):
            rt=live.LiveRuntime('patient',approver=lambda a,p:False)
        self.assertIn('Google-backed',server.tool_definitions(rt)[0]['description'])
        self.assertNotIn('Synthetic mode',server.tool_definitions(rt)[0]['description'])
    def test_connection_status_does_not_claim_current_write_verification(self):
        self.activate();calendar=MockCalendar()
        calendar.connection_status=lambda:{'calendar_read_verified':True,'write_verified':False}
        with patch.object(live,'google_clients',return_value=(None,calendar,MockSheets())):
            rt=live.LiveRuntime('doctor',approver=lambda a,p:False)
        with patch.object(live,'LIVE_LOCK',Path(self.tmp.name)/'live.lock'):
            result=rt.call('doctor_connection_status',{})
        self.assertFalse(result['write_verified'])
        self.assertEqual(result['mode'],'google')

class ApproverTests(unittest.TestCase):
    def setUp(self):
        self.state=fixture();self.cal=MockCalendar(self.state['events']);self.sheets=MockSheets()
        self.day=self.state['events']['a-demo']['start'][:10]
    def svc(self,approver,role='patient',subject='patient-a'):
        return Service(Identity(subject,role,'synthetic-clinic','synthetic',True),self.cal,self.sheets,approver=approver,synthetic_directory=True)
    def test_denied_dialog_blocks_write_and_consumes_token(self):
        s=self.svc(lambda a,p:False,subject='patient-c');args={'start':self.day+'T14:00:00+05:30','request_id':'approve-test-1'}
        d=s.call('book_my_appointment',args)
        with self.assertRaises(Denied):s.call('book_my_appointment',args|{'confirmation_token':d['confirmation_token']})
        self.assertEqual(self.cal.events,self.state['events'])
        with self.assertRaises(Denied):s.call('book_my_appointment',args|{'confirmation_token':d['confirmation_token']})
    def test_non_true_approval_is_denial(self):
        free_demo_day(self.cal.events,('a-demo',))  # patients book one appointment a day
        s=self.svc(lambda a,p:'yes');args={'start':self.day+'T14:00:00+05:30','request_id':'approve-test-2'}
        d=s.call('book_my_appointment',args)
        with self.assertRaises(Denied):s.call('book_my_appointment',args|{'confirmation_token':d['confirmation_token']})
    def test_doctor_booking_for_synthetic_patient_uses_approver(self):
        seen=[];doc=self.svc(lambda a,p:seen.append((a,p['owner'])) or True,'doctor','synthetic-doctor')
        args={'patient_reference':'patient-b','start':self.day+'T16:00:00+05:30','request_id':'doctor-live-1'}
        d=doc.call('doctor_book_appointment',args);r=doc.call('doctor_book_appointment',args|{'confirmation_token':d['confirmation_token']})
        self.assertTrue(r['calendar_confirmed']);self.assertEqual(seen,[('book','patient-b')])
    def test_agents_cannot_redirect_google_resources(self):
        doc=self.svc(lambda a,p:True,'doctor','synthetic-doctor')
        for field in ('calendar_id','spreadsheet_id','clinic_id'):
            self.assertNotIn(field,ARGUMENTS['doctor_configure_clinic']['properties']['changes']['properties'])
            with self.assertRaises(ValueError):doc.call('doctor_configure_clinic',{'changes':{field:'attacker-resource-123'}})
    def test_dialog_text_uses_clinic_timezone(self):
        text=live.describe('book',{'owner':'patient-a','start':'2030-01-07T10:00:00+08:00','end':'2030-01-07T10:20:00+08:00'},'Asia/Singapore')
        self.assertIn('10:00',text);self.assertIn('patient-a',text);self.assertIn('Asia/Singapore',text)
    def test_approver_fails_closed_off_macos(self):
        with patch.object(live.sys,'platform','linux'):self.assertFalse(live.macos_approver(lambda:'UTC')('book',{}))

if __name__=='__main__':unittest.main()
