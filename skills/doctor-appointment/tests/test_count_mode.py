"""Count mode: the doctor caps how many consultations and follow-ups a day takes,
instead of offering time slots. Hitting a cap records a doctor alert at once."""
import unittest,sys,copy,tempfile
from pathlib import Path
from datetime import date,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from core import *
from mock import MockCalendar,MockSheets,fixture

class CountModeTests(unittest.TestCase):
    def setUp(self):
        self.state=fixture();self.cal=MockCalendar(self.state['events']);self.sheets=MockSheets()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.alerts=AlertLog(Path(self.tmp.name)/'doctor-alerts.json')
        config=copy.deepcopy(DEFAULT)|{'booking_mode':'count','daily_caps':{'consultation':2,'follow_up':1}}
        def make(subject,role):
            s=Service(Identity(subject,role,'synthetic-clinic','synthetic',True),self.cal,self.sheets,config)
            s.alerts=self.alerts;return s
        self.a=make('patient-a','patient');self.b=make('patient-b','patient');self.doc=make('synthetic-doctor','doctor')
        self.services=(self.a,self.b,self.doc)
        self.day=self.state['events']['a-demo']['start'][:10]
        del self.cal.events['b-demo']  # Patient B has no history: a first-time patient
    def confirm(self,s,tool,args):
        first=s.call(tool,args);self.assertTrue(first.get('confirmation_required'),first)
        return s.call(tool,args|{'confirmation_token':first['confirmation_token']})
    def count_bookings(self,category=None):
        return [e for e in self.cal.events.values() if e.get('mode')=='count' and e['status']!='cancelled' and (category is None or e.get('category')==category)]
    def share_config(self,config):
        for s in self.services:s.config=config

    def test_lookup_returns_places_not_times(self):
        result=self.a.call('get_available_slots',{'day':self.day})
        self.assertEqual(result['mode'],'count');self.assertNotIn('slots',result)
        self.assertEqual(result['places']['consultation'],{'cap':2,'booked':0,'open':2})
        self.assertEqual(result['places']['follow_up'],{'cap':1,'booked':0,'open':1})
    def test_patient_with_history_is_a_follow_up(self):
        first=self.a.call('book_my_appointment',{'start':self.day,'request_id':'count-a-001'})
        self.assertEqual(first['details']['category'],'follow_up')
    def test_first_time_patient_is_asked_for_category(self):
        result=self.b.call('book_my_appointment',{'start':self.day,'request_id':'count-b-001'})
        self.assertTrue(result['category_required']);self.assertNotIn('confirmation_token',result)
        self.assertEqual(self.count_bookings(),[])
    def test_booking_holds_a_place_for_the_day(self):
        booked=self.confirm(self.b,'book_my_appointment',{'start':self.day,'request_id':'count-b-001','category':'consultation'})
        self.assertTrue(booked['calendar_confirmed'])
        self.assertEqual(booked['appointment']['category'],'consultation');self.assertEqual(booked['appointment']['mode'],'count')
        self.assertEqual(booked['appointment']['start'][:10],self.day)
        self.assertEqual(self.a.call('get_available_slots',{'day':self.day})['places']['consultation']['open'],1)
    def test_reaching_cap_alerts_doctor_once(self):
        self.confirm(self.a,'book_my_appointment',{'start':self.day,'request_id':'count-a-001','category':'consultation'})
        self.assertEqual(self.alerts.pending(),[])
        self.confirm(self.b,'book_my_appointment',{'start':self.day,'request_id':'count-b-001','category':'consultation'})
        pending=self.alerts.pending()
        self.assertEqual([(x['day'],x['category'],x['cap']) for x in pending],[(self.day,'consultation',2)])
        told=self.doc.call('doctor_get_schedule',{'day':self.day})['tell_doctor_first']
        self.assertIn('2 of 2 consultation places',told[0])
        self.assertNotIn('tell_doctor_first',self.doc.call('doctor_get_schedule',{'day':self.day}))
    def test_patient_never_sees_doctor_alerts(self):
        self.confirm(self.a,'book_my_appointment',{'start':self.day,'request_id':'count-a-001','category':'consultation'})
        self.confirm(self.b,'book_my_appointment',{'start':self.day,'request_id':'count-b-001','category':'consultation'})
        self.assertNotIn('tell_doctor_first',self.a.call('get_my_appointments',{}))
    def test_full_category_refused_other_category_open(self):
        self.confirm(self.a,'book_my_appointment',{'start':self.day,'request_id':'count-a-001'})  # follow-up cap 1
        self.cal.events.pop('a-demo');self.cal.events.pop('cancelled-demo')
        refused=self.b.call('book_my_appointment',{'start':self.day,'request_id':'count-b-001','category':'follow_up'})
        self.assertTrue(refused['full']);self.assertEqual(refused['category'],'follow_up')
        self.assertTrue(refused['alternatives']);self.assertNotIn(self.day,refused['alternatives'])
        self.assertEqual(len(self.count_bookings('follow_up')),1)
        self.assertTrue(self.b.call('book_my_appointment',{'start':self.day,'request_id':'count-b-002','category':'consultation'})['confirmation_required'])
    def test_cancellation_reopens_a_place(self):
        booked=self.confirm(self.a,'book_my_appointment',{'start':self.day,'request_id':'count-a-001'})
        self.confirm(self.a,'cancel_my_appointment',{'appointment_id':booked['appointment']['id']})
        self.assertEqual(self.a.call('get_available_slots',{'day':self.day})['places']['follow_up']['open'],1)
    def test_doctor_raises_one_days_cap(self):
        for who,rid in ((self.a,'count-a-001'),(self.b,'count-b-001')):
            self.confirm(who,'book_my_appointment',{'start':self.day,'request_id':rid,'category':'consultation'})
        saved=self.confirm(self.doc,'doctor_configure_clinic',{'changes':{'day_caps':{self.day:{'consultation':3}}}})
        self.share_config(saved['configuration'])
        self.assertEqual(saved['configuration']['day_caps'][self.day],{'consultation':3,'follow_up':1})
        self.assertEqual(saved['configuration']['daily_caps'],{'consultation':2,'follow_up':1})
        self.assertTrue(self.b.call('book_my_appointment',{'start':self.day,'request_id':'count-b-002','category':'consultation'})['confirmation_required'])
    def test_day_cap_override_merges_with_other_days(self):
        other=(date.fromisoformat(self.day)+timedelta(days=1)).isoformat()
        first=self.confirm(self.doc,'doctor_configure_clinic',{'changes':{'day_caps':{self.day:{'consultation':5}}}})
        self.share_config(first['configuration'])
        second=self.confirm(self.doc,'doctor_configure_clinic',{'changes':{'day_caps':{other:{'follow_up':4}}}})
        self.assertEqual(set(second['configuration']['day_caps']),{self.day,other})
    def test_doctor_booking_over_cap_needs_explicit_override(self):
        self.confirm(self.a,'book_my_appointment',{'start':self.day,'request_id':'count-a-001'})
        args={'patient_reference':'patient-b','start':self.day,'request_id':'count-doc-01','category':'follow_up'}
        refused=self.doc.call('doctor_book_appointment',args)
        self.assertTrue(refused['full']);self.assertNotIn('confirmation_token',refused)
        booked=self.confirm(self.doc,'doctor_book_appointment',args|{'allow_over_cap':True})
        self.assertTrue(booked['calendar_confirmed']);self.assertEqual(len(self.count_bookings('follow_up')),2)
    def test_count_bookings_never_block_slots_or_flag_conflicts(self):
        for who,rid in ((self.a,'count-a-001'),(self.b,'count-b-001')):
            self.confirm(who,'book_my_appointment',{'start':self.day,'request_id':rid,'category':'consultation'})
        ids={e['id'] for e in self.count_bookings()}
        self.assertFalse(any(set(pair)&ids for pair in self.cal.review_conflicts()))
        held=self.count_bookings()[0]
        self.assertNotIn((held['start'],held['end']),self.cal.busy(stamp(held['start']),stamp(held['end'])))
    def test_reschedule_moves_to_another_day_within_cap(self):
        booked=self.confirm(self.a,'book_my_appointment',{'start':self.day,'request_id':'count-a-001'})
        other=next(d for d in (date.fromisoformat(self.day)+timedelta(days=i) for i in range(1,8)) if d.weekday() in DEFAULT['working_days']).isoformat()
        moved=self.confirm(self.a,'reschedule_my_appointment',{'appointment_id':booked['appointment']['id'],'start':other})
        self.assertEqual(moved['appointment']['start'][:10],other);self.assertEqual(moved['appointment']['id'],booked['appointment']['id'])
    def test_closed_day_refused(self):
        sunday=next(d for d in (date.fromisoformat(self.day)+timedelta(days=i) for i in range(7)) if d.weekday() not in DEFAULT['working_days']).isoformat()
        result=self.b.call('book_my_appointment',{'start':sunday,'request_id':'count-b-001','category':'consultation'})
        self.assertTrue(result['closed']);self.assertEqual(self.count_bookings(),[])
    def test_doctor_schedule_shows_places_and_categories(self):
        self.confirm(self.b,'book_my_appointment',{'start':self.day,'request_id':'count-b-001','category':'consultation'})
        schedule=self.doc.call('doctor_get_schedule',{'day':self.day})
        self.assertEqual(schedule['places']['consultation'],{'cap':2,'booked':1,'open':1})
        self.assertEqual([e['category'] for e in schedule['appointments'] if e.get('mode')=='count'],['consultation'])
    def test_moved_day_booking_notice_names_days_not_times(self):
        booked=self.confirm(self.doc,'doctor_book_appointment',{'patient_reference':'patient-b','start':self.day,'request_id':'count-doc-01','category':'consultation'})
        notice=self.b.call('get_my_appointments',{})['tell_patient_first'][0]
        self.assertNotRegex(notice,r'\d:\d\d');self.assertIn('booked a place for you',notice)

class CountConfigTests(unittest.TestCase):
    def test_older_config_gains_count_defaults(self):
        old={k:v for k,v in copy.deepcopy(DEFAULT).items() if k not in ('booking_mode','daily_caps','day_caps')}
        c=validate_config(old)
        self.assertEqual(c['booking_mode'],'slots');self.assertIn('consultation',c['daily_caps'])
    def test_invalid_count_settings_rejected(self):
        for bad in ({'booking_mode':'tokens'},{'daily_caps':{'consultation':-1,'follow_up':1}},
                    {'daily_caps':{'consultation':2}},{'day_caps':{'not-a-date':{'consultation':2}}},
                    {'day_caps':{'2026-10-20':{'walk_in':2}}}):
            with self.assertRaises(ValueError):validate_config(copy.deepcopy(DEFAULT)|bad)



class CountRuntimeTests(unittest.TestCase):
    def test_practice_runtime_records_and_shows_alert_across_sessions(self):
        from server import PracticeRuntime
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        path=Path(tmp.name)/'practice-state.json'
        state=fixture();state['config'].update(booking_mode='count',daily_caps={'consultation':1,'follow_up':1})
        atomic(path,state)
        patient=PracticeRuntime('patient','patient-b',path);doctor=PracticeRuntime('doctor',state_path=path)
        day=state['events']['b-demo']['start'][:10]
        args={'start':day,'request_id':'runtime-b-01'}
        first=patient.call('book_my_appointment',args)
        patient.call('book_my_appointment',args|{'confirmation_token':first['confirmation_token']})
        self.assertTrue((Path(tmp.name)/'doctor-alerts.json').exists())
        self.assertIn('tell_doctor_first',doctor.call('doctor_get_schedule',{'day':day}))

class CountSetupTests(unittest.TestCase):
    def test_setup_saves_count_mode_and_caps(self):
        import admin,server,io,contextlib,json
        from unittest.mock import patch
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        (root/'config').mkdir()
        with patch.object(admin,'ROOT',root),patch.object(server,'LOCAL_STATE',root/'config'/'local-bookings.json'),contextlib.redirect_stdout(io.StringIO()):
            admin.clinic_settings(['booking_mode=count','daily_caps={"consultation":12,"follow_up":6}'])
        saved=json.loads((root/'config'/'google-clinic.json').read_text())
        self.assertEqual((saved['booking_mode'],saved['daily_caps']),('count',{'consultation':12,'follow_up':6}))

if __name__=='__main__':unittest.main()
