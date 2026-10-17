"""Patients learn about clinic-side changes to their appointments; no Google or model calls."""
import sys,unittest,unittest.mock
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from core import DEFAULT,Service,Identity,clinic_change
from mock import MockCalendar,MockSheets,fixture

class ClinicChangeTests(unittest.TestCase):
    def setUp(self):
        state=fixture();self.cal=MockCalendar(state['events']);self.sheets=MockSheets()
        self.day=state['events']['a-demo']['start'][:10]
        self.patient=Service(Identity('patient-a','patient',DEFAULT['clinic_id'],'synthetic',True),self.cal,self.sheets)
        self.doctor=Service(Identity('synthetic-doctor','doctor',DEFAULT['clinic_id'],'synthetic',True),self.cal,self.sheets)
    def confirmed(self,svc,tool,args):
        draft=svc.call(tool,args);return svc.call(tool,args|{'confirmation_token':draft['confirmation_token']})
    def book(self,hour='14:00',request='patient-book-1'):
        return self.confirmed(self.patient,'book_my_appointment',{'start':self.day+'T'+hour+':00+05:30','request_id':request})['appointment']['id']
    def state_start(self,ident):return self.cal.events[ident]['start']
    def mine(self,ident):
        return next(e for e in self.patient.call('get_my_appointments',{})['appointments'] if e['id']==ident)

    def test_patient_own_booking_and_changes_raise_no_notice(self):
        ident=self.book()
        self.assertNotIn('clinic_change',self.mine(ident))
        self.confirmed(self.patient,'reschedule_my_appointment',{'appointment_id':ident,'start':self.day+'T14:40:00+05:30'})
        self.assertNotIn('clinic_change',self.mine(ident))
        self.confirmed(self.patient,'cancel_my_appointment',{'appointment_id':ident})
        self.assertNotIn('clinic_change',self.mine(ident))
    def test_doctor_move_is_reported_with_previous_time(self):
        ident=self.book()
        self.confirmed(self.doctor,'doctor_reschedule_appointment',{'appointment_id':ident,'start':self.day+'T15:00:00+05:30'})
        change=self.mine(ident)['clinic_change']
        self.assertEqual(change['type'],'moved_by_clinic');self.assertEqual(change['previous_start'],self.day+'T14:00:00+05:30')
        text=self.patient.call('get_available_slots',{'day':self.day})['tell_patient_first'][0]
        self.assertIn('2:00 pm–2:30 pm to ',text);self.assertIn('3:00 pm–3:30 pm.',text)
    def test_doctor_cancellation_is_reported(self):
        ident=self.book()
        self.confirmed(self.doctor,'doctor_cancel_appointment',{'appointment_id':ident})
        self.assertEqual(self.mine(ident)['clinic_change']['type'],'cancelled_by_clinic')
    def test_direct_calendar_edits_are_reported(self):
        ident=self.book()
        event=self.cal.events[ident]
        event['start']=self.day+'T16:00:00+05:30'  # dragged in Google Calendar
        self.assertEqual(self.mine(ident)['clinic_change']['type'],'moved_by_clinic')
        event['status']='cancelled'  # deleted in Google Calendar
        self.assertEqual(self.mine(ident)['clinic_change']['type'],'cancelled_by_clinic')
    def test_doctor_booking_for_patient_is_reported(self):
        out=self.confirmed(self.doctor,'doctor_book_appointment',{'patient_reference':'patient-a','start':self.day+'T16:00:00+05:30','request_id':'doctor-book-1'})
        self.assertEqual(self.mine(out['appointment']['id'])['clinic_change']['type'],'booked_by_clinic')
    def test_doctor_move_of_booking_from_before_tracking_is_reported(self):
        ident=self.book();del self.cal.events[ident]['agreed']
        self.confirmed(self.doctor,'doctor_reschedule_appointment',{'appointment_id':ident,'start':self.day+'T15:00:00+05:30'})
        self.assertEqual(self.mine(ident)['clinic_change']['type'],'moved_by_clinic')
    def test_every_patient_answer_carries_outstanding_changes(self):
        from datetime import date,timedelta
        ident=self.book()
        self.confirmed(self.doctor,'doctor_cancel_appointment',{'appointment_id':ident})
        info=self.patient.call('get_clinic_information',{})
        self.assertEqual(len(info['tell_patient_first']),1);self.assertTrue(info['tell_patient_first'][0].startswith('The clinic cancelled your appointment on '))
        other=Service(Identity('patient-b','patient',DEFAULT['clinic_id'],'synthetic',True),self.cal,self.sheets)
        self.assertNotIn('tell_patient_first',other.call('get_clinic_information',{}))
        self.assertIn('tell_patient_first',self.patient.call('get_my_appointments',{}))
    def test_startup_banner_shows_each_change_once(self):
        import tempfile,notices,server
        from core import NoticeLog
        ident=self.book()
        self.confirmed(self.doctor,'doctor_cancel_appointment',{'appointment_id':ident})
        patient=self.patient
        class Runtime:
            def __init__(rt,role,name):rt.service=patient
            def call(rt,name,args):return patient.call(name,args)
        with tempfile.TemporaryDirectory() as d,unittest.mock.patch.object(server,'make_runtime',Runtime):
            log=NoticeLog(Path(d)/'seen.json')
            first=notices.banner('patient-a',log)
            self.assertEqual(len(first),1);self.assertTrue(first[0].startswith('The clinic cancelled your appointment on '))
            self.assertEqual(notices.banner('patient-a',log),[])
            self.confirmed(self.patient,'reschedule_my_appointment',{'appointment_id':self.book('15:20','patient-book-2'),'start':self.day+'T16:00:00+05:30'})
            self.assertEqual(notices.banner('patient-a',log),[])  # patient's own change: nothing new
    def test_patients_can_only_book_and_move_to_listed_slots(self):
        # Default grid: 30 min + 10 min buffer from 09:00, restarting at 14:00 after lunch.
        listed=self.patient.call('get_available_slots',{'day':self.day,'preferred_start':self.day+'T14:15:00+05:30'})
        self.assertNotIn(self.day+'T14:15:00+05:30',listed['slots']);self.assertFalse(listed['requested_start_available'])
        self.assertEqual(listed['requested_start_status'],'not_a_clinic_appointment_time')
        lunch=self.patient.call('get_available_slots',{'day':self.day,'preferred_start':self.day+'T13:20:00+05:30'})
        self.assertEqual(lunch['requested_start_status'],'outside_clinic_hours')
        taken=self.patient.call('get_available_slots',{'day':self.day,'preferred_start':self.state_start('a-demo')})
        self.assertEqual(taken['requested_start_status'],'already_booked')
        self.assertIn(self.day+'T14:00:00+05:30',listed['slots']);self.assertIn(self.day+'T14:40:00+05:30',listed['slots'])
        off=self.patient.call('book_my_appointment',{'start':self.day+'T14:15:00+05:30','request_id':'patient-off-grid'})
        self.assertTrue(off['conflict']);self.assertNotIn('confirmation_token',off)
        ident=self.book()
        moved=self.patient.call('reschedule_my_appointment',{'appointment_id':ident,'start':self.day+'T15:05:00+05:30'})
        self.assertTrue(moved['conflict']);self.assertNotIn('confirmation_token',moved)
    def test_doctor_may_use_any_free_time(self):
        out=self.confirmed(self.doctor,'doctor_book_appointment',{'patient_reference':'patient-b','start':self.day+'T14:15:00+05:30','request_id':'doctor-off-grid'})
        self.assertTrue(out['calendar_confirmed'])
    def test_each_change_is_told_once_across_startup_and_chat(self):
        import tempfile
        from core import NoticeLog
        ident=self.book()
        self.confirmed(self.doctor,'doctor_cancel_appointment',{'appointment_id':ident})
        with tempfile.TemporaryDirectory() as d:
            self.patient.notices_seen=NoticeLog(Path(d)/'seen.json')
            first=self.patient.call('get_available_slots',{'day':self.day})
            self.assertEqual(len(first['tell_patient_first']),1);self.assertIn('slots',first)
            self.assertNotIn('tell_patient_first',self.patient.call('get_clinic_information',{}))
            self.assertNotIn('tell_patient_first',self.patient.call('get_my_appointments',{}))
            # The appointment still shows as changed by the clinic when listed.
            self.assertEqual(self.mine(ident)['clinic_change']['type'],'cancelled_by_clinic')
    def test_length_change_in_calendar_is_reported(self):
        ident=self.book()
        self.cal.events[ident]['end']=self.day+'T15:10:00+05:30'  # resized in Google Calendar
        self.assertEqual(self.mine(ident)['clinic_change']['type'],'moved_by_clinic')
        text=self.patient.call('get_clinic_information',{})['tell_patient_first'][0]
        self.assertIn('2:00 pm–2:30 pm to ',text);self.assertIn('2:00 pm–3:10 pm.',text)
    def test_appointments_from_before_tracking(self):
        legacy={'id':'x','kind':'appointment','start':'s','end':'e','status':'cancelled','clinic_status':'confirmed'}
        self.assertEqual(clinic_change(legacy)['type'],'cancelled_by_clinic')
        self.assertIsNone(clinic_change(legacy|{'clinic_status':'cancelled'}))
        self.assertIsNone(clinic_change(legacy|{'status':'confirmed'}))

if __name__=='__main__':unittest.main()
