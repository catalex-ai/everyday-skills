"""One patient per session, chosen by the launcher with --patient: any safe ID is
a patient, with a record (their name) made on first use. Patient A and B are the
demo patients. No Google or model calls."""
import copy,json,re,subprocess,sys,tempfile,unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from core import *
from mock import MockCalendar,MockSheets,fixture,free_demo_day
from server import PracticeRuntime,tool_definitions

PACKAGE=Path(__file__).resolve().parents[1]
P1='clinic-patient_0001'
P2='clinic-patient_0002'

class PatientIdTests(unittest.TestCase):
    def test_patient_ids(self):
        cases=[('demo A','patient-a',True),('demo B','patient-b',True),('letters digits dash underscore',P1,True),('one character','x',True),
               ('128 characters','a'*128,True),('129 characters','a'*129,False),('empty','',False),('space','patient a',False),
               ('slash','../patient',False),('dot','patient.a',False),('newline','patient\n',False),('not a string',7,False)]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'
            for name,subject,ok in cases:
                with self.subTest(name):
                    self.assertEqual(valid_patient(subject),ok)
                    if ok:self.assertEqual(PracticeRuntime('patient',subject,path).service.identity.subject,subject)
                    else:
                        with self.assertRaises(ValueError):PracticeRuntime('patient',subject,path)
    def test_server_patient_flag(self):
        lines='\n'.join(json.dumps(x) for x in ({'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},{'jsonrpc':'2.0','id':2,'method':'tools/list'}))+'\n'
        server=[sys.executable,str(PACKAGE/'tools'/'server.py'),'--role','patient','--patient']
        cases=[('demo patient','patient-b',0),('any safe ID',P1,0),('unsafe ID','../x',2),('too long','a'*129,2)]
        for name,patient,code in cases:
            with self.subTest(name):
                out=subprocess.run(server+[patient],input=lines,capture_output=True,text=True)
                self.assertEqual(out.returncode,code,out.stderr)
                if code:self.assertEqual(out.stdout,'')
                else:self.assertEqual({t['name'] for t in json.loads(out.stdout.splitlines()[1])['result']['tools']},PATIENT)

class PatientTests(unittest.TestCase):
    def setUp(self):
        state=fixture();self.cal=MockCalendar(state['events']);self.sheets=MockSheets()
        self.day=state['events']['a-demo']['start'][:10]
        free_demo_day(self.cal.events)
        # No move cutoff, so these tests never depend on the time of day they run.
        self.config=copy.deepcopy(DEFAULT)|{'cancel_cutoff_hours':0}
        self.patients=PatientDirectory()
        self.p1=self.make(P1,'patient');self.p2=self.make(P2,'patient');self.a=self.make('patient-a','patient');self.doc=self.make('synthetic-doctor','doctor')
    def make(self,subject,role):
        s=Service(Identity(subject,role,'synthetic-clinic','synthetic',True),self.cal,self.sheets,self.config);s.patients=self.patients;return s
    def at(self,hour):return self.day+'T'+hour+':00+05:30'
    def confirm(self,s,tool,args):
        first=s.call(tool,args);self.assertTrue(first.get('confirmation_required'),first)
        return first,s.call(tool,args|{'confirmation_token':first['confirmation_token']})
    def book(self,s,hour='14:00',request='patient-book-1'):
        return self.confirm(s,'book_my_appointment',{'start':self.at(hour),'request_id':request})[1]['appointment']['id']

    def test_patients_stay_isolated(self):
        mine=self.book(self.p1);theirs=self.book(self.p2,hour='15:20',request='patient-book-2')
        for name,service,expected in (('patient 1',self.p1,{mine}),('patient 2',self.p2,{theirs}),('Patient A',self.a,{'a-demo','cancelled-demo'})):
            with self.subTest(name):self.assertEqual({e['id'] for e in service.call('get_my_appointments',{})['appointments']},expected)
        for name,tool,args in (('cancel','cancel_my_appointment',{'appointment_id':theirs}),('move','reschedule_my_appointment',{'appointment_id':theirs,'start':self.at('16:00')})):
            with self.subTest('patient 1 cannot '+name+' patient 2'):
                with self.assertRaises(Denied):self.p1.call(tool,args)
                self.assertEqual(self.cal.events[theirs]['status'],'confirmed')

    def test_patient_details(self):
        self.assertEqual(self.p1.call('get_my_details',{}),{'name':None})
        self.assertIn(P1,self.patients.memory)  # made on first use
        cases=[('plain','Asha Rao','Asha Rao'),('spaces collapse','  Asha   Rao ','Asha Rao'),('longest','a'*80,'a'*80),
               ('empty','',None),('blank','   ',None),('too long','a'*81,None),('control character','Asha\x00',None),('not a string',5,None)]
        for name,given,saved in cases:
            with self.subTest(name):
                if saved is None:
                    with self.assertRaises(ValueError):self.p1.call('set_my_name',{'name':given})
                else:
                    self.assertEqual(self.p1.call('set_my_name',{'name':given}),{'saved':True,'name':saved})
                    self.assertEqual(self.p1.call('get_my_details',{}),{'name':saved})
        self.assertEqual(self.p2.call('get_my_details',{}),{'name':None})  # each patient has their own
        with self.assertRaises(ValueError):self.p1.call('set_my_name',{'name':'Asha','patient':P2})

    def test_doctor_results_name_the_patient(self):
        self.p1.call('set_my_name',{'name':'Asha Rao'})
        named=self.book(self.p1);unnamed=self.book(self.a,hour='15:20',request='patient-book-2')
        schedule={e['id']:e for e in self.doc.call('doctor_get_schedule',{'day':self.day})['appointments']}
        cases=[
            ('schedule, named patient',schedule[named],P1,'Asha Rao'),
            ('schedule, unnamed patient',schedule[unnamed],'patient-a',None),
            ('appointment detail',self.doc.call('doctor_get_appointment',{'appointment_id':named}),P1,'Asha Rao'),
            ('doctor move',self.confirm(self.doc,'doctor_reschedule_appointment',{'appointment_id':named,'start':self.at('16:00')})[1]['appointment'],P1,'Asha Rao'),
            ('doctor cancel',self.confirm(self.doc,'doctor_cancel_appointment',{'appointment_id':named})[1]['appointment'],P1,'Asha Rao'),
            ('cancel again',self.doc.call('doctor_cancel_appointment',{'appointment_id':named})['appointment'],P1,'Asha Rao'),
        ]
        for name,result,reference,patient_name in cases:
            with self.subTest(name):
                self.assertEqual(result.get('patient_reference'),reference);self.assertEqual(result.get('patient_name'),patient_name)
        for e in self.p1.call('get_my_appointments',{})['appointments']:
            self.assertNotIn('patient_name',e);self.assertNotIn('patient_reference',e)

    def test_move_proposal_shows_no_raw_event(self):
        ident=self.book(self.p1)
        self.cal.events[ident]['description']='private note'
        proposal=self.p1.call('reschedule_my_appointment',{'appointment_id':ident,'start':self.at('16:00')})
        self.assertRegex(proposal['details']['version'],r'^[0-9a-f]{64}$')
        self.assertNotIn('private note',json.dumps(proposal));self.assertNotIn('"owner"',json.dumps(proposal['details']))

    def test_doctor_books_any_known_patient(self):
        self.p1.call('get_my_appointments',{})  # patient 1 has used the Patient Assistant
        cases=[('demo patient','patient-b',True),('known patient',P1,True),('never seen','clinic-patient_9999',False),('malformed','a b',False)]
        for i,(name,reference,ok) in enumerate(cases):
            with self.subTest(name):
                args={'patient_reference':reference,'start':self.at(('14:00','14:40','15:20','16:00')[i]),'request_id':f'doctor-book-{i:04d}'}
                if not ok:
                    with self.assertRaises(ValueError):self.doc.call('doctor_book_appointment',args)
                    continue
                booked=self.confirm(self.doc,'doctor_book_appointment',args)[1]
                self.assertEqual(self.cal.events[booked['appointment']['id']]['owner'],reference)
        # A patient with bookings stays bookable even if the patient file was cleared.
        self.patients.memory.clear()
        args={'patient_reference':P1,'start':self.at('09:40'),'request_id':'doctor-book-cleared'}
        self.assertTrue(self.confirm(self.doc,'doctor_book_appointment',args)[1]['calendar_confirmed'])
        self.assertNotIn('enum',ARGUMENTS['doctor_book_appointment']['properties']['patient_reference'])

class PatientStorageTests(unittest.TestCase):
    def test_local_store_keeps_patients_across_sessions(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json';state=fixture();free_demo_day(state['events']);path.write_text(json.dumps(state))
            patient=PracticeRuntime('patient',P1,path);doctor=PracticeRuntime('doctor',state_path=path)
            patient.call('set_my_name',{'name':'Asha Rao'})
            finder=Service(Identity('slot-finder','patient','synthetic-clinic','synthetic',True),MockCalendar(state['events']),None)
            args={'start':finder.grid(date.fromisoformat(fixture()['events']['b-demo']['start'][:10]))[-1].isoformat(),'request_id':'local-store-1'}
            proposal=patient.call('book_my_appointment',args)
            ident=patient.call('book_my_appointment',args|{'confirmation_token':proposal['confirmation_token']})['appointment']['id']
            self.assertEqual(json.loads((Path(d)/'patients.json').read_text())[P1]['name'],'Asha Rao')
            self.assertEqual(doctor.call('doctor_get_appointment',{'appointment_id':ident})['patient_name'],'Asha Rao')
            self.assertEqual([e['id'] for e in PracticeRuntime('patient',P1,path).call('get_my_appointments',{})['appointments']],[ident])
    def test_tool_list_offers_patient_details(self):
        with tempfile.TemporaryDirectory() as d:
            tools={t['name']:t for t in tool_definitions(PracticeRuntime('patient',P1,Path(d)/'state.json'))}
        self.assertEqual(tools['set_my_name']['inputSchema']['required'],['name'])
        self.assertEqual(tools['get_my_details']['inputSchema']['properties'],{})

class PatientToolAccessTests(unittest.TestCase):
    def test_guard_allows_patient_details_only_for_patients(self):
        from tool_guard import decide
        for name in ('mcp__clinic__get_my_details','mcp__clinic__set_my_name'):
            with self.subTest(name):
                self.assertTrue(decide('patient',{'tool_name':name}));self.assertFalse(decide('doctor',{'tool_name':name}))
        for name in ('Bash','Read','Write','Edit','ToolSearch','WebFetch','mcp__other__set_my_name'):
            with self.subTest(name):self.assertFalse(decide('patient',{'tool_name':name}))
    def test_settings_and_codex_list_every_patient_tool(self):
        import tomllib
        settings=json.loads((PACKAGE/'patient-agent'/'.claude'/'settings.json').read_text())
        self.assertEqual(set(settings['permissions']['allow']),{'mcp__clinic__'+t for t in PATIENT}|{'Skill(clinic-role:appointments)'})
        self.assertIn('ToolSearch',settings['permissions']['deny'])
        config=tomllib.loads((PACKAGE/'patient-agent'/'.codex'/'config.toml').read_text())
        self.assertEqual(set(config['mcp_servers']['clinic']['enabled_tools']),PATIENT)
    def test_instructions_cover_patient_details(self):
        patient=(PACKAGE/'patient-agent'/'AGENTS.md').read_text();doctor=(PACKAGE/'doctor-agent'/'AGENTS.md').read_text()
        cases=[('patient reads details',patient,'get_my_details'),('patient saves the name',patient,'set_my_name'),('doctor uses names',doctor,'patient_name')]
        for name,text,phrase in cases:
            with self.subTest(name):self.assertIn(phrase,text)

if __name__=='__main__':unittest.main()
