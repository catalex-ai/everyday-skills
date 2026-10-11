"""Human terminal operations; NOT exposed through patient/doctor MCP."""
import argparse,json,sys
from pathlib import Path
from core import ROOT,DEFAULT,atomic,validate_config,lock
from mock import fixture

def live_gate():
    # No production escape hatch. Gateway and effective OS boundary must be
    # implemented and independently audited before real-patient support.
    raise PermissionError('Real-patient mode disabled: gateway identity and OS credential boundary are unverified')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=['practice-reset','practice-demo','google-connect','google-status','google-revoke','open-spreadsheet','google-configure','synthetic-google-test','audit','native-prepare']);p.add_argument('--client',type=Path);p.add_argument('--calendar-id');p.add_argument('--spreadsheet-id')
    a=p.parse_args()
    if a.operation=='native-prepare':
        # Reuse an existing native Codex login without reading or copying its
        # contents. This is provider auth, not Google OAuth. No launcher is made.
        import os
        existing=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'auth.json'
        for role in ('patient','doctor'):
            home=ROOT/(role+'-agent')/'.codex';home.mkdir(exist_ok=True)
            target=home/'auth.json'
            if existing.is_file() and not target.exists():target.symlink_to(existing.resolve())
        print('Native folders prepared. Existing Codex login reused if available; otherwise run codex login with the folder CODEX_HOME. Google consent is separate.')
        return
    if a.operation=='practice-reset':
        with lock(ROOT/'config'/'practice-state.lock'):atomic(ROOT/'config'/'practice-state.json',fixture())
        print('Synthetic practice state reset. No Google access.');return
    if a.operation=='practice-demo':
        from server import PracticeRuntime
        for role,patient in [('patient','patient-a'),('patient','patient-b'),('doctor','patient-a')]:
            r=PracticeRuntime(role,patient)
            if role=='patient':value=r.call('get_my_appointments',{})
            else:
                state=json.loads((ROOT/'config'/'practice-state.json').read_text());day=next(iter(state['events'].values()))['start'][:10];value=r.call('doctor_get_schedule',{'day':day})
            print(json.dumps({'role':role,'identity':patient if role=='patient' else 'synthetic-doctor','result':value},indent=2))
        return
    if a.operation=='audit':
        from audit import audit
        print(json.dumps(audit(),indent=2));return
    config_path=ROOT/'config'/'google-clinic.json'
    if a.operation=='google-configure':
        # Human-owned terminal conversation, never sourced from model args.
        c=json.loads(config_path.read_text()) if config_path.exists() else dict(DEFAULT)
        for field in DEFAULT:
            if field=='clinic_id':continue
            old=c[field];raw=input(f'{field} [{json.dumps(old)}] (Enter retains): ').strip()
            if raw:c[field]=json.loads(raw) if field in ('working_days','breaks','duration_minutes','buffer_minutes') else raw
        atomic(config_path,validate_config(c));print('Non-secret Google configuration saved.');return
    from google_adapter import connect,revoke,credentials,Calendar,Sheets
    if a.operation=='google-revoke':print(json.dumps(revoke()));return
    c=validate_config(json.loads(config_path.read_text())) if config_path.exists() else dict(DEFAULT)
    cal=a.calendar_id or c['calendar_id'];sheet=a.spreadsheet_id or c['spreadsheet_id']
    if not cal or not sheet:raise ValueError('Run google-configure to select explicit calendar and spreadsheet IDs')
    if a.operation=='google-connect':
        if not a.client or not a.client.is_file():raise ValueError('Provide --client pointing to downloaded Desktop OAuth client JSON outside repository')
        print('Human terminal OAuth operation. No secrets are returned to the model.');print(json.dumps(connect(a.client,cal,sheet)));return
    creds=credentials();calendar=Calendar(creds,cal);sheets=Sheets(creds,sheet)
    if a.operation=='google-status':calendar.verify();sheets.verify();print('Google Calendar and Sheets read access verified.');return
    if a.operation=='open-spreadsheet':print(json.dumps(sheets.open()));return
    if a.operation=='synthetic-google-test':
        # Security gate required by the requested ordering, even for synthetic
        # writes into a real Google resource. No API mutation before this gate.
        live_gate()
        from verification import verify_google
        print(json.dumps(verify_google(calendar,sheets,c),indent=2))

if __name__=='__main__':
    try:main()
    except Exception as e:
        # OAuth libraries may include HTTP bodies/credentials in exception text.
        if isinstance(e,(ValueError,PermissionError,FileNotFoundError)):print(str(e),file=sys.stderr)
        else:print(type(e).__name__+': operation failed; no secrets displayed',file=sys.stderr)
        sys.exit(1)
