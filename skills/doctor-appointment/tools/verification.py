"""Human-consented live Google synthetic workflow. Run from the admin terminal only.

Writes happen through the same Service path the agents use, and every write is
approved by the human in the out-of-band approver (the macOS dialog in live use).
All checks are API readbacks; nothing is inferred from model output.
"""
import hashlib,secrets
from core import Service,Identity,stamp

def verify_google(calendar,sheets,config,start,approver,log=print):
    """Book, sync, duplicate-check, isolate, cancel and re-sync one synthetic event.

    Prints the stable event ID before writing so an interruption can be recovered.
    """
    calendar.verify();sheets.verify();stamp(start)
    owner='synthetic-verification-'+secrets.token_hex(8)
    patient=Service(Identity(owner,'patient',config['clinic_id'],'synthetic',True),calendar,sheets,config,approver=approver)
    doctor=Service(Identity('verification-doctor','doctor',config['clinic_id'],'synthetic',True),calendar,sheets,config,approver=approver)
    other=Service(Identity('synthetic-other','patient',config['clinic_id'],'synthetic',True),calendar,sheets,config)
    req='verification-'+secrets.token_hex(12)
    event_id=hashlib.sha256(f'{config["clinic_id"]}:{owner}:{req}'.encode()).hexdigest()
    report={'id':event_id,'start':start}
    log('Synthetic recovery event ID: '+event_id)
    args={'start':start,'request_id':req}
    draft=patient.call('book_my_appointment',args)
    if not draft.get('confirmation_required'):return report|{'not_created':True,'result':draft}
    log('Approve the CREATE dialog on screen to write one synthetic event.')
    booked=patient.call('book_my_appointment',args|{'confirmation_token':draft['confirmation_token']})
    if not booked.get('calendar_confirmed'):return report|{'not_created':True,'result':booked}
    found=calendar.get(event_id)
    report['calendar_write_readback']=bool(found) and found.get('owner')==owner and found.get('start')==stamp(start).isoformat() and found.get('status')=='confirmed'
    first=doctor.call('doctor_sync_register',{})
    rows=sheets.read_records()  # raises on duplicate IDs
    report['sheets_row_synced']=bool(first.get('synced')) and rows.get(event_id,{}).get('status')=='confirmed'
    # Duplicate prevention: same request ID is idempotent and creates no new event;
    # repeated reconciliation overwrites by stable ID instead of appending.
    retry=patient.call('book_my_appointment',args)
    owned=patient.call('get_my_appointments',{})['appointments']
    second=doctor.call('doctor_sync_register',{});rows2=sheets.read_records()
    report['duplicate_prevention']={'retry_returned_existing':retry.get('calendar_confirmed') is True and retry.get('appointment',{}).get('id')==event_id and 'confirmation_required' not in retry,
        'calendar_events_for_owner':len(owned),'register_rows_stable':bool(second.get('synced')) and len(rows2)==len(rows),
        'register_id_count':sum(1 for k in rows2 if k==event_id)}
    report['patient_isolation']=event_id in {x['id'] for x in owned} and event_id not in {x['id'] for x in other.call('get_my_appointments',{})['appointments']}
    log('Approve the CANCEL dialog on screen to cancel the synthetic event.')
    cargs={'appointment_id':event_id};cdraft=doctor.call('doctor_cancel_appointment',cargs)
    try:cancelled=doctor.call('doctor_cancel_appointment',cargs|{'confirmation_token':cdraft['confirmation_token']})
    except Exception as e:return report|{'cancellation':'not approved or failed: '+type(e).__name__,'cleanup_required':True}
    after=calendar.get(event_id)
    report['calendar_cancel_readback']=bool(cancelled.get('calendar_confirmed')) and bool(after) and after.get('status')=='cancelled'
    final=doctor.call('doctor_sync_register',{})
    report['sheets_cancel_synced']=bool(final.get('synced')) and sheets.read_records().get(event_id,{}).get('status')=='cancelled'
    dup=report['duplicate_prevention']
    report['passed']=all([report['calendar_write_readback'],report['sheets_row_synced'],dup['retry_returned_existing'],dup['calendar_events_for_owner']==1,
        dup['register_rows_stable'],dup['register_id_count']==1,report['patient_isolation'],report['calendar_cancel_readback'],report['sheets_cancel_synced']])
    return report
