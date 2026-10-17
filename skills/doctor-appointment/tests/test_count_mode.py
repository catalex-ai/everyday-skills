"""Count mode: the doctor caps how many consultations and follow-ups a day takes,
instead of offering time slots. Hitting a cap records a doctor alert at once."""
import unittest,sys,copy,tempfile
from pathlib import Path
from datetime import date,timedelta,datetime
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from core import *
from mock import MockCalendar,MockSheets,fixture,free_demo_day

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
        free_demo_day(self.cal.events)
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
        self.assertEqual(result['places'],{'consultation':{'has_room':True},'follow_up':{'has_room':True}})  # no counts for patients
        self.assertEqual(self.doc.places(date.fromisoformat(self.day))['consultation'],{'cap':2,'booked':0,'open':2})
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
        self.assertEqual(booked['appointment']['day'],self.day);self.assertNotIn('start',booked['appointment'])  # the queue time is the doctor's
        self.assertEqual(self.doc.places(date.fromisoformat(self.day))['consultation']['open'],1)
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
        self.assertEqual(self.doc.places(date.fromisoformat(self.day))['follow_up']['open'],1)
    def test_doctor_raises_one_days_cap(self):
        for who,rid in ((self.a,'count-a-001'),(self.b,'count-b-001')):
            self.confirm(who,'book_my_appointment',{'start':self.day,'request_id':rid,'category':'consultation'})
        saved=self.confirm(self.doc,'doctor_configure_clinic',{'changes':{'day_caps':{self.day:{'consultation':3}}}})
        self.share_config(saved['configuration'])
        self.assertEqual(saved['configuration']['day_caps'][self.day],{'consultation':3,'follow_up':1})
        self.assertEqual(saved['configuration']['daily_caps'],{'consultation':2,'follow_up':1})
        c=Service(Identity('patient-c','patient','synthetic-clinic','synthetic',True),self.cal,self.sheets,saved['configuration'])
        self.assertTrue(c.call('book_my_appointment',{'start':self.day,'request_id':'count-c-001','category':'consultation'})['confirmation_required'])
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
        self.assertEqual(moved['appointment']['day'],other);self.assertEqual(moved['appointment']['id'],booked['appointment']['id'])
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



class TotalCapTests(unittest.TestCase):
    """One shared cap: the doctor need not split new patients from follow-ups."""
    def setUp(self):
        self.state=fixture();self.cal=MockCalendar(self.state['events']);self.sheets=MockSheets()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.alerts=AlertLog(Path(self.tmp.name)/'doctor-alerts.json')
        config=copy.deepcopy(DEFAULT)|{'booking_mode':'count','daily_caps':{'total':2}}
        def make(subject,role):
            s=Service(Identity(subject,role,'synthetic-clinic','synthetic',True),self.cal,self.sheets,config)
            s.alerts=self.alerts;return s
        self.a=make('patient-a','patient');self.b=make('patient-b','patient');self.doc=make('synthetic-doctor','doctor')
        self.day=self.state['events']['a-demo']['start'][:10]
        free_demo_day(self.cal.events)
        del self.cal.events['b-demo']
    def confirm(self,s,tool,args):
        first=s.call(tool,args);self.assertTrue(first.get('confirmation_required'),first)
        return s.call(tool,args|{'confirmation_token':first['confirmation_token']})
    def test_total_cap_is_valid_and_a_mix_is_not(self):
        validate_config(copy.deepcopy(DEFAULT)|{'daily_caps':{'total':10}})
        with self.assertRaises(ValueError):validate_config(copy.deepcopy(DEFAULT)|{'daily_caps':{'total':10,'consultation':5}})
    def test_new_patient_is_not_asked_for_category(self):
        booked=self.confirm(self.b,'book_my_appointment',{'start':self.day,'request_id':'total-b-001'})
        self.assertEqual(booked['appointment']['category'],'consultation')
    def test_any_visit_type_shares_the_places_and_alerts_once_full(self):
        self.confirm(self.a,'book_my_appointment',{'start':self.day,'request_id':'total-a-001'})
        self.assertEqual(self.a.call('get_available_slots',{'day':self.day})['places'],{'total':{'has_room':True}})
        self.assertEqual(self.doc.places(date.fromisoformat(self.day)),{'total':{'cap':2,'booked':1,'open':1}})
        self.confirm(self.b,'book_my_appointment',{'start':self.day,'request_id':'total-b-001'})
        self.assertEqual([(x['category'],x['cap']) for x in self.alerts.pending()],[('total',2)])
        told=self.doc.call('doctor_get_schedule',{'day':self.day})['tell_doctor_first']
        self.assertIn('2 of 2 patient places',told[0])
        c=Service(Identity('patient-c','patient','synthetic-clinic','synthetic',True),self.cal,self.sheets,self.a.config)
        full=c.call('book_my_appointment',{'start':self.day,'request_id':'total-c-001'})
        self.assertTrue(full['full'])
    def test_one_day_total_override(self):
        first=self.doc.call('doctor_configure_clinic',{'changes':{'day_caps':{self.day:{'total':5}}}})
        saved=self.doc.call('doctor_configure_clinic',{'changes':{'day_caps':{self.day:{'total':5}}},'confirmation_token':first['confirmation_token']})
        self.assertEqual(saved['configuration']['day_caps'][self.day],{'total':5})
        self.assertEqual(self.doc.places(date.fromisoformat(self.day))['total']['cap'],5)
    def test_split_day_override_on_total_needs_both_counts(self):
        self.assertEqual(combine_caps({'total':10},{'consultation':6,'follow_up':4}),{'consultation':6,'follow_up':4})
        self.assertEqual(combine_caps({'consultation':6,'follow_up':4},{'total':12}),{'total':12})
        self.assertEqual(combine_caps({'consultation':6,'follow_up':4},{'consultation':8}),{'consultation':8,'follow_up':4})

class QueueTests(unittest.TestCase):
    """Each count-mode place is the next queue_minutes of the day, first come first served."""
    def setUp(self):
        self.state=fixture();self.cal=MockCalendar(self.state['events']);self.sheets=MockSheets()
        self.day=self.state['events']['a-demo']['start'][:10];free_demo_day(self.cal.events)
        self.config=copy.deepcopy(DEFAULT)|{'booking_mode':'count','daily_caps':{'total':50},'opening':'17:00','closing':'17:20','breaks':[]}
        self.n=0
    def patient(self,subject):
        return Service(Identity(subject,'patient','synthetic-clinic','synthetic',True),self.cal,self.sheets,self.config)
    def book(self,subject):
        s=self.patient(subject);self.n+=1;args={'start':self.day,'request_id':f'queue-{self.n:04d}'}
        first=s.call('book_my_appointment',args)
        if 'confirmation_token' not in first:return first
        return s.call('book_my_appointment',args|{'confirmation_token':first['confirmation_token']})
    def times(self):
        return sorted((e['start'][11:16],e['end'][11:16]) for e in self.cal.events.values() if e.get('mode')=='count' and e['status']!='cancelled')
    def test_bookings_take_consecutive_five_minute_places(self):
        for who in ('patient-a','patient-b','patient-c'):self.book(who)
        self.assertEqual(self.times(),[('17:00','17:05'),('17:05','17:10'),('17:10','17:15')])
    def test_cancelled_place_is_not_refilled(self):
        first=self.book('patient-a');self.book('patient-b')
        s=self.patient('patient-a');args={'appointment_id':first['appointment']['id']}
        s.call('cancel_my_appointment',args|{'confirmation_token':s.call('cancel_my_appointment',args)['confirmation_token']})
        self.book('patient-c')
        self.assertEqual(self.times(),[('17:05','17:10'),('17:10','17:15')])
    def test_queue_skips_blocked_time_and_fills_up_at_closing(self):
        self.cal.events['blocked-demo'].update(start=self.day+'T17:05:00+05:30',end=self.day+'T17:10:00+05:30')
        for who in ('patient-a','patient-b','patient-c'):self.book(who)
        self.assertEqual(self.times(),[('17:00','17:05'),('17:10','17:15'),('17:15','17:20')])
        self.assertTrue(self.book('patient-c')['already_booked_that_day'])
        self.assertTrue(self.book('patient-d')['full'])
    def test_patient_sees_the_day_doctor_sees_the_time(self):
        booked=self.book('patient-a')
        self.assertEqual(booked['appointment']['day'],self.day);self.assertNotIn('start',booked['appointment'])
        mine=self.patient('patient-a').call('get_my_appointments',{})['appointments']
        self.assertTrue(all('start' not in e for e in mine if e.get('mode')=='count'))
        doc=Service(Identity('synthetic-doctor','doctor','synthetic-clinic','synthetic',True),self.cal,self.sheets,self.config)
        starts=[e['start'][11:16] for e in doc.call('doctor_get_schedule',{'day':self.day})['appointments'] if e.get('mode')=='count']
        self.assertEqual(starts,['17:00'])
    def test_queue_minutes_is_configurable(self):
        self.config['queue_minutes']=10
        for who in ('patient-a','patient-b'):self.book(who)
        self.assertEqual(self.times(),[('17:00','17:10'),('17:10','17:20')])

class OneBookingPerDayTests(unittest.TestCase):
    """A patient books at most one appointment a day; the doctor may add another."""
    def setUp(self):
        self.state=fixture();self.cal=MockCalendar(self.state['events']);self.sheets=MockSheets()
        self.day=self.state['events']['a-demo']['start'][:10]
        self.a=Service(Identity('patient-a','patient','synthetic-clinic','synthetic',True),self.cal,self.sheets)
        self.doc=Service(Identity('synthetic-doctor','doctor','synthetic-clinic','synthetic',True),self.cal,self.sheets)
    def test_patient_cannot_book_a_second_slot_that_day(self):
        result=self.a.call('book_my_appointment',{'start':self.day+'T14:00:00+05:30','request_id':'second-0001'})
        self.assertTrue(result['already_booked_that_day']);self.assertEqual(result['appointment']['id'],'a-demo')
        self.assertNotIn('confirmation_token',result)
    def test_patient_cannot_move_another_booking_onto_that_day(self):
        other=next(d for d in (date.fromisoformat(self.day)+timedelta(days=i) for i in range(1,8)) if d.weekday() in DEFAULT['working_days']).isoformat()
        args={'start':other+'T14:00:00+05:30','request_id':'second-0002'}
        booked=self.a.call('book_my_appointment',args|{'confirmation_token':self.a.call('book_my_appointment',args)['confirmation_token']})
        moved=self.a.call('reschedule_my_appointment',{'appointment_id':booked['appointment']['id'],'start':self.day+'T14:00:00+05:30'})
        self.assertTrue(moved['already_booked_that_day'])
    def test_count_mode_patient_cannot_book_twice(self):
        for s in (self.a,self.doc):s.config=copy.deepcopy(DEFAULT)|{'booking_mode':'count','daily_caps':{'total':10}}
        result=self.a.call('book_my_appointment',{'start':self.day,'request_id':'second-0003'})
        self.assertTrue(result['already_booked_that_day'])
    def test_doctor_may_add_a_second_appointment(self):
        args={'patient_reference':'patient-a','start':self.day+'T14:00:00+05:30','request_id':'doctor-second-1'}
        first=self.doc.call('doctor_book_appointment',args)
        self.assertTrue(first['confirmation_required'])

class BookingWindowTests(unittest.TestCase):
    """Patients book at most booking_window_days ahead; the doctor can book any day."""
    def setUp(self):
        self.state=fixture();self.cal=MockCalendar(self.state['events']);self.sheets=MockSheets()
        today=datetime.now(ZoneInfo(DEFAULT['timezone'])).date()
        working=lambda start:next(d for d in (start+timedelta(days=i) for i in range(7)) if d.weekday() in DEFAULT['working_days'])
        self.inside=working(today+timedelta(days=1))
        self.beyond=working(today+timedelta(days=8))
        self.a=Service(Identity('patient-c','patient','synthetic-clinic','synthetic',True),self.cal,self.sheets)
        self.doc=Service(Identity('synthetic-doctor','doctor','synthetic-clinic','synthetic',True),self.cal,self.sheets)
    def at(self,d,t='14:00'):return f'{d.isoformat()}T{t}:00+05:30'
    def test_patient_cannot_see_or_book_beyond_a_week(self):
        listed=self.a.call('get_available_slots',{'day':self.beyond.isoformat()})
        self.assertTrue(listed['beyond_booking_window']);self.assertNotIn('slots',listed)
        result=self.a.call('book_my_appointment',{'start':self.at(self.beyond),'request_id':'window-0001'})
        self.assertTrue(result['beyond_booking_window']);self.assertNotIn('confirmation_token',result)
        self.assertTrue(self.a.call('book_my_appointment',{'start':self.at(self.inside),'request_id':'window-0002'})['confirmation_required'])
    def test_patient_cannot_move_beyond_a_week(self):
        args={'start':self.at(self.inside),'request_id':'window-0003'}
        booked=self.a.call('book_my_appointment',args|{'confirmation_token':self.a.call('book_my_appointment',args)['confirmation_token']})
        moved=self.a.call('reschedule_my_appointment',{'appointment_id':booked['appointment']['id'],'start':self.at(self.beyond)})
        self.assertTrue(moved['beyond_booking_window'])
    def test_doctor_books_any_day_and_can_widen_the_window(self):
        self.assertTrue(self.doc.call('doctor_book_appointment',{'patient_reference':'patient-a','start':self.at(self.beyond),'request_id':'window-doc-1'})['confirmation_required'])
        self.a.config['booking_window_days']=14
        self.assertIn('slots',self.a.call('get_available_slots',{'day':self.beyond.isoformat()}))
        self.assertEqual(self.a.call('get_clinic_information',{})['booking_window_days'],14)
    def test_count_mode_alternatives_stay_inside_the_window(self):
        self.a.config=self.a.config|{'booking_mode':'count','daily_caps':{'total':1}}
        last=datetime.now(ZoneInfo(DEFAULT['timezone'])).date()+timedelta(days=7)
        self.assertTrue(all(date.fromisoformat(d)<=last for d in self.a.open_days('consultation',date.today())))

class AbuseGuardTests(unittest.TestCase):
    """Weekly booking limit (cancelled not counted), no changes to past
    appointments, and no-shows that stop self-booking."""
    def setUp(self):
        self.cal=MockCalendar({});self.sheets=MockSheets()
        self.p=Service(Identity('patient-a','patient','synthetic-clinic','synthetic',True),self.cal,self.sheets)
        self.doc=Service(Identity('synthetic-doctor','doctor','synthetic-clinic','synthetic',True),self.cal,self.sheets)
        today=datetime.now(ZoneInfo(DEFAULT['timezone'])).date()
        self.days=[d for d in (today+timedelta(days=i) for i in range(1,8)) if d.weekday() in DEFAULT['working_days']]
        self.n=0
    def confirm(self,s,tool,args):
        first=s.call(tool,args)
        return s.call(tool,args|{'confirmation_token':first['confirmation_token']}) if 'confirmation_token' in first else first
    def book(self,d,who=None):
        self.n+=1;return self.confirm(who or self.p,'book_my_appointment',{'start':f'{d.isoformat()}T14:00:00+05:30','request_id':f'guard-{self.n:04d}'})
    def past(self,ident,status='confirmed',days_ago=2):
        start=datetime.now(ZoneInfo(DEFAULT['timezone'])).replace(microsecond=0)-timedelta(days=days_ago)
        self.cal.events[ident]={'id':ident,'owner':'patient-a','clinic':'synthetic-clinic','kind':'appointment','status':status,
                                'start':start.isoformat(),'end':(start+timedelta(minutes=30)).isoformat()}
    def test_weekly_limit_ignores_cancelled_bookings(self):
        booked=[self.book(d) for d in self.days[:3]]
        self.assertTrue(all(b['calendar_confirmed'] for b in booked))
        self.assertTrue(self.book(self.days[3])['weekly_limit_reached'])
        self.confirm(self.p,'cancel_my_appointment',{'appointment_id':booked[0]['appointment']['id']})
        self.assertTrue(self.book(self.days[3])['calendar_confirmed'])
    def test_doctor_is_not_limited(self):
        for d in self.days[:3]:self.book(d)
        args={'patient_reference':'patient-a','start':f'{self.days[3].isoformat()}T14:00:00+05:30','request_id':'guard-doc-1'}
        self.assertTrue(self.confirm(self.doc,'doctor_book_appointment',args)['calendar_confirmed'])
    def test_patient_cannot_cancel_or_move_a_past_appointment(self):
        self.past('old-visit')
        self.assertTrue(self.p.call('cancel_my_appointment',{'appointment_id':'old-visit'})['in_the_past'])
        self.assertTrue(self.p.call('reschedule_my_appointment',{'appointment_id':'old-visit','start':f'{self.days[0].isoformat()}T14:00:00+05:30'})['in_the_past'])
        self.assertTrue(self.confirm(self.doc,'doctor_cancel_appointment',{'appointment_id':'old-visit'})['calendar_confirmed'])
    def test_two_no_shows_stop_self_booking_until_cleared(self):
        self.past('missed-1',days_ago=3);self.past('missed-2',days_ago=5);self.past('missed-old',days_ago=10)
        self.confirm(self.doc,'doctor_mark_no_show',{'appointment_id':'missed-old'})
        self.assertTrue(self.book(self.days[2])['calendar_confirmed'])  # a no-show older than 7 days doesn't count
        for ident in ('missed-1','missed-2'):
            marked=self.confirm(self.doc,'doctor_mark_no_show',{'appointment_id':ident})
            self.assertEqual(marked['appointment']['status'],'no_show')
        blocked=self.book(self.days[0]);self.assertTrue(blocked['booking_blocked']);self.assertNotIn('confirmation_token',blocked)
        args={'patient_reference':'patient-a','start':f'{self.days[0].isoformat()}T14:00:00+05:30','request_id':'guard-doc-2'}
        self.assertTrue(self.confirm(self.doc,'doctor_book_appointment',args)['calendar_confirmed'])
        self.confirm(self.doc,'doctor_mark_no_show',{'appointment_id':'missed-1','no_show':False})
        self.assertTrue(self.book(self.days[1])['calendar_confirmed'])
    def test_only_past_appointments_can_be_marked(self):
        future=self.book(self.days[0])['appointment']['id']
        self.assertTrue(self.doc.call('doctor_mark_no_show',{'appointment_id':future})['conflict'])
        self.assertNotIn('doctor_mark_no_show',PATIENT)
    def soon(self,ident,hours):
        start=datetime.now(ZoneInfo(DEFAULT['timezone'])).replace(microsecond=0)+timedelta(hours=hours)
        self.cal.events[ident]={'id':ident,'owner':'patient-a','clinic':'synthetic-clinic','kind':'appointment','status':'confirmed',
                                'start':start.isoformat(),'end':(start+timedelta(minutes=30)).isoformat()}
    def test_late_move_refused_and_late_cancel_counts_like_a_no_show(self):
        self.soon('late-1',3);self.soon('late-2',5)
        moved=self.p.call('reschedule_my_appointment',{'appointment_id':'late-1','start':f'{self.days[-1].isoformat()}T14:00:00+05:30'})
        self.assertTrue(moved['too_late_to_move'])
        proposal=self.p.call('cancel_my_appointment',{'appointment_id':'late-1'})
        self.assertTrue(proposal['details']['late_cancellation'])
        for ident in ('late-1','late-2'):self.confirm(self.p,'cancel_my_appointment',{'appointment_id':ident})
        self.assertTrue(self.cal.events['late-1']['late_cancel'])
        self.assertTrue(self.book(self.days[0])['booking_blocked'])
        self.confirm(self.doc,'doctor_mark_no_show',{'appointment_id':'late-1','no_show':False})  # the doctor excuses one
        self.assertTrue(self.book(self.days[0])['calendar_confirmed'])
    def test_early_cancel_is_free_and_cutoff_can_be_turned_off(self):
        self.soon('early',30);self.confirm(self.p,'cancel_my_appointment',{'appointment_id':'early'})
        self.assertNotIn('late_cancel',self.cal.events['early'])
        self.p.config['cancel_cutoff_hours']=0;self.soon('soon',2)
        self.assertNotIn('late_cancellation',self.p.call('cancel_my_appointment',{'appointment_id':'soon'})['details'])
    def test_doctor_asked_once_who_came_after_a_finished_day(self):
        self.doc.notices_seen=NoticeLog(Path(tempfile.mkdtemp())/'seen.json')
        z=ZoneInfo(DEFAULT['timezone']);today=datetime.now(z).date()
        d=next(x for x in (today-timedelta(days=i) for i in range(1,8)) if x.weekday() in DEFAULT['working_days'])
        start=datetime.combine(d,datetime.min.time(),z)+timedelta(hours=10)
        self.cal.events['done']={'id':'done','owner':'patient-a','clinic':'synthetic-clinic','kind':'appointment','status':'confirmed',
                                 'start':start.isoformat(),'end':(start+timedelta(minutes=30)).isoformat()}
        first=self.doc.call('doctor_get_schedule',{'day':today.isoformat()})['ask_doctor_about_attendance']
        self.assertEqual([(x['day'],[a['patient_reference'] for a in x['appointments']]) for x in first],[(d.isoformat(),['patient-a'])])
        self.assertNotIn('ask_doctor_about_attendance',self.doc.call('doctor_get_schedule',{'day':today.isoformat()}))
        self.assertNotIn('ask_doctor_about_attendance',self.p.call('get_my_appointments',{}))
    def test_approval_dialog_names_day_and_no_show(self):
        from live import describe
        self.assertIn('Day: 2026-10-20',describe('book',{'owner':'patient-a','day':'2026-10-20'},'Asia/Kolkata'))
        self.assertIn('missed (no-show)',describe('mark_no_show',{'owner':'patient-a','start':'2026-10-15T09:00:00+05:30','no_show':True},'Asia/Kolkata'))

class AvailabilityPrivacyTests(unittest.TestCase):
    """Patients can't read the doctor's schedule off availability: a few times per
    check, no "already booked", and a daily cap on checks."""
    def setUp(self):
        self.state=fixture();self.cal=MockCalendar(self.state['events']);self.sheets=MockSheets()
        self.day=self.state['events']['a-demo']['start'][:10]
        self.p=Service(Identity('patient-c','patient','synthetic-clinic','synthetic',True),self.cal,self.sheets)
        self.doc=Service(Identity('synthetic-doctor','doctor','synthetic-clinic','synthetic',True),self.cal,self.sheets)
    def test_patient_sees_three_times_nearest_the_request(self):
        everything=self.doc.slots(self.day)['slots']
        self.assertGreater(len(everything),3)
        self.assertEqual(self.p.call('get_available_slots',{'day':self.day})['slots'],everything[:3])
        near=self.p.call('get_available_slots',{'day':self.day,'preferred_start':self.day+'T15:20:00+05:30'})['slots']
        self.assertEqual(near,[self.day+'T14:40:00+05:30',self.day+'T15:20:00+05:30',self.day+'T16:00:00+05:30'])
    def test_taken_time_is_only_not_available(self):
        taken=self.p.call('get_available_slots',{'day':self.day,'preferred_start':self.state['events']['a-demo']['start']})  # Patient A's 9:00
        self.assertEqual(taken['requested_start_status'],'not_available')
    def test_daily_lookup_limit(self):
        self.p.lookups=LookupLog(Path(tempfile.mkdtemp())/'lookups.json');self.p.config['daily_lookup_limit']=2
        for _ in range(2):self.assertIn('slots',self.p.call('get_available_slots',{'day':self.day}))
        stopped=self.p.call('book_my_appointment',{'start':self.day+'T14:00:00+05:30','request_id':'lookup-0001'})
        self.assertTrue(stopped['lookup_limit_reached']);self.assertNotIn('confirmation_token',stopped)
        self.assertTrue(self.p.call('get_my_appointments',{})['appointments'] is not None)  # other requests still work

class CountRuntimeTests(unittest.TestCase):
    def test_practice_runtime_records_and_shows_alert_across_sessions(self):
        from server import PracticeRuntime
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        path=Path(tmp.name)/'practice-state.json'
        state=fixture();state['config'].update(booking_mode='count',daily_caps={'consultation':1,'follow_up':1})
        day=state['events']['b-demo']['start'][:10];free_demo_day(state['events'])
        atomic(path,state)
        patient=PracticeRuntime('patient','patient-b',path);doctor=PracticeRuntime('doctor',state_path=path)
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
