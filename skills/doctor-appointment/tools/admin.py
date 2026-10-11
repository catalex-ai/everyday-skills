"""Human terminal operations; NOT exposed through patient/doctor MCP."""
import argparse,json,sys
from pathlib import Path
from urllib.parse import urlparse
from core import ROOT,DEFAULT,atomic,validate_config,lock
from mock import fixture

def live_gate():
    # No production escape hatch. Gateway and effective OS boundary must be
    # implemented and independently audited before real-patient support.
    raise PermissionError('Real-patient mode disabled: gateway identity and OS credential boundary are unverified')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=['practice-reset','practice-demo','google-connect','google-setup','google-status','google-revoke','open-spreadsheet','google-configure','synthetic-google-test','audit','native-prepare']);p.add_argument('--client',type=Path);p.add_argument('--calendar-id');p.add_argument('--spreadsheet-id')
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
    if a.operation=='google-setup':
        # This is an operator-owned terminal conversation. State the product
        # limitation before opening a browser so consent cannot be mistaken for
        # permission to schedule real patients.
        print('Google setup only verifies clinic Calendar and Sheets access. Real-patient scheduling remains disabled until the identity gateway and OS credential boundary are independently verified.')
        c=json.loads(config_path.read_text()) if config_path.exists() else dict(DEFAULT)
        client=a.client
        if client is None:client=Path(input('Path to downloaded Desktop OAuth client JSON (outside this package): ').strip()).expanduser()
        client=client.expanduser().resolve()
        if not client.is_file():raise FileNotFoundError('Desktop OAuth client JSON path does not exist')
        try:client.relative_to(ROOT.resolve())
        except ValueError:pass
        else:raise ValueError('Keep the Desktop OAuth client JSON outside this package')
        title=None
        if a.spreadsheet_id:
            # Compatibility with an explicit existing register ID supplied by
            # an operator who already knows it. Interactive setup uses a URL.
            sheet=a.spreadsheet_id.strip()
        else:
            choice=input('Register choice: [1] Create a new register  [2] Use an existing spreadsheet: ').strip()
            if choice=='1':
                title=input('Title for the new clinic register: ').strip()
                if not title or len(title)>200:raise ValueError('Enter a register title of 1–200 characters')
                sheet=None
            elif choice=='2':
                raw=input('Paste the full Google Sheets URL: ').strip()
                parsed=urlparse(raw)
                parts=parsed.path.split('/')
                if parsed.scheme!='https' or parsed.netloc not in ('docs.google.com','www.docs.google.com') or len(parts)<4 or parts[1]!='spreadsheets' or parts[2]!='d':
                    raise ValueError('Use a Google Sheets URL such as https://docs.google.com/spreadsheets/d/…/edit')
                sheet=parts[3]
                if not sheet or not all(ch.isalnum() or ch in '_-' for ch in sheet):raise ValueError('The Google Sheets URL has an invalid spreadsheet ID')
            else:raise ValueError('Choose 1 to create a register or 2 to use an existing spreadsheet')
        import re
        if sheet is not None and not re.fullmatch(r'[A-Za-z0-9_-]{10,200}',sheet):raise ValueError('Provide a valid spreadsheet ID')
        from google_adapter import authorize,list_calendars,store_credentials,Calendar,Sheets
        print('Starting browser consent now. Approve the requested Calendar and Sheets access. Real-patient scheduling remains disabled.')
        creds=authorize(client)
        calendars=list_calendars(creds)
        if not calendars:raise ValueError('No writable clinic calendars are available to this Google account')
        if a.calendar_id:
            cal=a.calendar_id.strip()
            if not cal or cal=='primary':raise ValueError('Select an explicit clinic calendar; the literal primary shortcut is not allowed')
            calendar=Calendar(creds,cal);calendar.verify()
            cal_name=next((x.get('summary',cal) for x in calendars if x.get('id')==cal),cal)
        else:
            for i,item in enumerate(calendars,1):print(f"[{i}] {item.get('summary','(unnamed calendar)')}")
            raw=input('Select clinic calendar number: ').strip()
            if not raw.isdigit() or not 1<=int(raw)<=len(calendars):raise ValueError('Select one of the listed writable calendars')
            selected=calendars[int(raw)-1];cal=selected['id'];cal_name=selected.get('summary',cal)
            if not cal or cal=='primary':raise ValueError('Google returned an invalid calendar ID')
            calendar=Calendar(creds,cal);calendar.verify()
        if title is not None:
            sheets=Sheets.create(creds,title)
            sheet=sheets.ident
        else:
            sheets=Sheets(creds,sheet)
            sheets.initialize_register()
        sheets.verify()
        # Persist credentials only after both chosen resources pass verification.
        store_credentials(creds)
        c['calendar_id']=cal;c['spreadsheet_id']=sheet
        atomic(config_path,validate_config(c))
        print(f"Google setup complete. Calendar: {cal_name}. Register: https://docs.google.com/spreadsheets/d/{sheet}/edit")
        print('Authorization stored in macOS Keychain; both resources verified.')
        return
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
    if not cal or not sheet:raise ValueError('Google is not configured. Run google-setup --client PATH to choose a writable calendar and create a register or paste an existing Google Sheets URL.')
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

def run():
    try:main()
    except Exception as e:
        # OAuth libraries may include HTTP bodies/credentials in exception text.
        if isinstance(e,(ValueError,PermissionError,FileNotFoundError)):print(str(e),file=sys.stderr)
        else:print(type(e).__name__+': operation failed; no secrets displayed',file=sys.stderr)
        sys.exit(1)

if __name__=='__main__':run()
