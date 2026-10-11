"""Human-consented Google synthetic workflow. admin.live_gate runs first."""
import hashlib,json,secrets
from datetime import datetime
from core import Service,Identity,stamp,public_event

def verify_google(calendar,sheets,config,ask=input):
    """No credentials or raw event bodies in output; all mutations require consent.

    Invoked only by human terminal admin after security approval; never MCP.
    An interrupted run prints stable event ID before writing for manual recovery.
    """
    calendar.verify();sheets.verify()
    start=ask('Synthetic test slot (ISO date/time including offset): ').strip()
    stamp(start)
    if ask('Type CREATE SYNTHETIC TEST to create one event in the configured calendar: ').strip()!='CREATE SYNTHETIC TEST':return {'aborted':True}
    owner='synthetic-verification-'+secrets.token_hex(8)
    patient=Service(Identity(owner,'patient',config['clinic_id'],'synthetic',True),calendar,sheets,config)
    doctor=Service(Identity('verification-doctor','doctor',config['clinic_id'],'synthetic',True),calendar,sheets,config)
    req='verification-'+secrets.token_hex(12)
    event_id=hashlib.sha256(f'{config["clinic_id"]}:{owner}:{req}'.encode()).hexdigest()
    print('Synthetic recovery event ID: '+event_id)
    args={'start':start,'request_id':req};draft=patient.call('book_my_appointment',args)
    if not draft.get('confirmation_required'):return {'not_created':True,'result':draft}
    booked=patient.call('book_my_appointment',args|{'confirmation_token':draft['confirmation_token']})
    if not booked.get('calendar_confirmed'):return {'not_created':True,'result':booked}
    first=doctor.call('doctor_sync_register',{})
    if not first['synced']:return {'calendar_confirmed':True,'id':event_id,'sync_failed':True,'cleanup_required':True}
    sheets.open()
    if ask('Verify the synthetic row in the opened spreadsheet. Type ROW VERIFIED: ').strip()!='ROW VERIFIED':return {'id':event_id,'row_verification_pending':True,'cleanup_required':True}
    again=doctor.call('doctor_sync_register',{})
    if not again['synced']:return {'id':event_id,'sync_failed':True,'cleanup_required':True}
    records=sheets.read_records()
    if event_id not in records:raise RuntimeError('Synthetic row missing after reconciliation')
    # read_records rejects duplicate IDs; a second full reconciliation does not append.
    if ask('Type CANCEL SYNTHETIC TEST to cancel the test event: ').strip()!='CANCEL SYNTHETIC TEST':return {'id':event_id,'cleanup_required':True}
    args={'appointment_id':event_id};draft=doctor.call('doctor_cancel_appointment',args)
    cancelled=doctor.call('doctor_cancel_appointment',args|{'confirmation_token':draft['confirmation_token']})
    final=doctor.call('doctor_sync_register',{})
    if not final['synced'] or sheets.read_records().get(event_id,{}).get('status')!='cancelled':return {'id':event_id,'cancellation':cancelled,'cancellation_sync_verified':False}
    other=Service(Identity('synthetic-other','patient',config['clinic_id'],'synthetic',True),calendar,sheets,config)
    mine=patient.call('get_my_appointments',{})['appointments'];theirs=other.call('get_my_appointments',{})['appointments']
    if event_id not in {x['id'] for x in mine} or event_id in {x['id'] for x in theirs}:raise RuntimeError('Patient isolation verification failed')
    from audit import audit
    permission_report=audit()
    return {'id':event_id,'calendar_verified':True,'row_human_verified':True,'no_duplicate_verified':True,'cancellation_sync_verified':True,'patient_isolation_verified':True,'runtime_audit':permission_report}
