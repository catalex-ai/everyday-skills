"""Human terminal operations; NOT exposed through patient/doctor MCP."""
import argparse,json,sys
from pathlib import Path
from urllib.parse import urlparse
from core import ROOT,DEFAULT,atomic,validate_config,lock
from mock import fixture

class AdminError(Exception):
    """Trusted, nonsecret message for validation performed by this CLI."""

class AdminPermissionError(AdminError, PermissionError):
    """Trusted CLI denial that preserves the PermissionError contract."""

def live_gate():
    # No production escape hatch. Gateway and effective OS boundary must be
    # implemented and independently audited before real-patient support.
    raise AdminPermissionError('Real-patient mode disabled: gateway identity and OS credential boundary are unverified')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=['status','clinic-settings','use-laptop','list-calendars','google-setup','activate','google-status','google-revoke','open-spreadsheet','hide-cancelled','synthetic-google-test','practice-reset','practice-demo','google-connect','google-configure','audit','native-prepare']);p.add_argument('--client',type=Path);p.add_argument('--start');p.add_argument('--calendar-id');p.add_argument('--spreadsheet-id')
    p.add_argument('--calendar',help='Clinic calendar name as shown in Google Calendar');p.add_argument('--new-register',metavar='TITLE');p.add_argument('--register-url')
    p.add_argument('--runtime',choices=['codex','claude'],help='native-prepare: app the double-click shortcuts open')
    p.add_argument('--set',action='append',default=[],metavar='FIELD=VALUE',help='clinic-settings: e.g. clinic_name="Dr Rao Clinic" opening=09:00 working_days=[0,1,2,3,4] booking_mode=count daily_caps=\'{"consultation":10,"follow_up":5}\'')
    a=p.parse_args()
    if a.operation=='status':print(json.dumps(status(),indent=2));return
    if a.operation=='clinic-settings':clinic_settings(a.set);return
    if a.operation=='use-laptop':use_laptop();return
    if a.operation=='native-prepare' and a.runtime:
        # Remembered so start.sh and the double-click shortcuts open the chosen app.
        (ROOT/'config').mkdir(exist_ok=True);(ROOT/'config'/'runtime').write_text(a.runtime+'\n')
        if a.runtime=='claude':print('Shortcuts will open Claude Code.');return
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
    if a.operation=='list-calendars':
        from google_adapter import list_calendars,store_credentials
        creds,fresh=google_sign_in(a.client);calendars=list_calendars(creds)
        # Keep a sign-in that works so google-setup reuses it instead of asking again.
        if fresh:store_credentials(creds)
        print(json.dumps([x.get('summary','(unnamed calendar)') for x in calendars],indent=2));return
    if a.operation=='google-setup':
        # Operator-owned setup. Answers may come from flags (the setup assistant
        # asks the doctor in chat) or, in a human terminal, from prompts.
        c=json.loads(config_path.read_text()) if config_path.exists() else dict(DEFAULT)
        title=None
        if a.spreadsheet_id:
            # Compatibility with an explicit existing register ID supplied by
            # an operator who already knows it. Interactive setup uses a URL.
            sheet=a.spreadsheet_id.strip()
        elif a.new_register:title=a.new_register.strip();sheet=None
        elif a.register_url:sheet=sheet_from_url(a.register_url)
        else:
            choice=input('Register choice: [1] Create a new register  [2] Use an existing spreadsheet: ').strip()
            if choice=='1':title=input('Title for the new clinic register: ').strip();sheet=None
            elif choice=='2':sheet=sheet_from_url(input('Paste the full Google Sheets URL: '))
            else:raise AdminError('Choose 1 to create a register or 2 to use an existing spreadsheet')
        if title is not None and (not title or len(title)>200):raise AdminError('Enter a register title of 1–200 characters')
        import re
        if sheet is not None and not re.fullmatch(r'[A-Za-z0-9_-]{10,200}',sheet):raise AdminError('Provide a valid spreadsheet ID')
        from google_adapter import list_calendars,store_credentials,Calendar,Sheets
        creds,fresh=google_sign_in(a.client)
        calendars=list_calendars(creds)
        if not calendars:raise AdminError('No writable clinic calendars are available to this Google account')
        if a.calendar_id:
            cal=a.calendar_id.strip()
            if not cal or cal=='primary':raise AdminError('Select an explicit clinic calendar; the literal primary shortcut is not allowed')
            cal_name=next((x.get('summary',cal) for x in calendars if x.get('id')==cal),cal)
        else:
            if a.calendar:
                matches=[x for x in calendars if x.get('summary','').strip().casefold()==a.calendar.strip().casefold()]
                if len(matches)!=1:raise AdminError('No single writable calendar is named '+json.dumps(a.calendar)+'. Available: '+', '.join(json.dumps(x.get('summary','')) for x in calendars))
                selected=matches[0]
            else:
                for i,item in enumerate(calendars,1):print(f"[{i}] {item.get('summary','(unnamed calendar)')}")
                raw=input('Select clinic calendar number: ').strip()
                if not raw.isdigit() or not 1<=int(raw)<=len(calendars):raise AdminError('Select one of the listed writable calendars')
                selected=calendars[int(raw)-1]
            cal=selected['id'];cal_name=selected.get('summary',cal)
            if not cal or cal=='primary':raise AdminError('Google returned an invalid calendar ID')
        calendar=Calendar(creds,cal);calendar.verify()
        if title is not None:
            sheets=Sheets.create(creds,title)
            sheet=sheets.ident
        else:
            sheets=Sheets(creds,sheet)
            sheets.initialize_register()
        sheets.verify()
        # Persist new credentials only after both chosen resources pass verification.
        if fresh:store_credentials(creds)
        c['calendar_id']=cal;c['spreadsheet_id']=sheet
        atomic(config_path,validate_config(c))
        print(f"Google setup complete. Calendar: {cal_name}. Register: https://docs.google.com/spreadsheets/d/{sheet}/edit")
        print('Google sign-in '+('stored in macOS Keychain' if fresh else 'reused from macOS Keychain')+'; calendar and register verified. Next: activate.')
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
    if a.operation=='google-revoke':
        from live import ACTIVATION
        result=revoke()
        if ACTIVATION.exists():ACTIVATION.unlink()  # no live mode without stored authorization
        print(json.dumps(result));return
    c=validate_config(json.loads(config_path.read_text())) if config_path.exists() else dict(DEFAULT)
    cal=a.calendar_id or c['calendar_id'];sheet=a.spreadsheet_id or c['spreadsheet_id']
    if not cal or not sheet:raise AdminError('Google is not configured. Run google-setup --client PATH to choose a writable calendar and create a register or paste an existing Google Sheets URL.')
    if a.operation=='google-connect':
        if not a.client or not a.client.is_file():raise AdminError('Provide --client pointing to downloaded Desktop OAuth client JSON outside repository')
        print('Human terminal OAuth operation. No secrets are returned to the model.');print(json.dumps(connect(a.client,cal,sheet)));return
    creds=credentials();calendar=Calendar(creds,cal);sheets=Sheets(creds,sheet)
    if a.operation=='google-status':calendar.verify();sheets.verify();print('Google Calendar and Sheets read access verified.');return
    if a.operation=='open-spreadsheet':print(json.dumps(sheets.open()));return
    if a.operation=='hide-cancelled':
        print(str(calendar.hide_cancelled(c['clinic_id']))+' cancelled appointment(s) removed from the calendar view.');return
    if a.operation=='activate':
        # Minimal check that the stored sign-in reaches the chosen resources, then switch.
        from datetime import datetime,timezone,timedelta
        from live import ACTIVATION,STORAGE,resources
        calendar.verify();now=datetime.now().astimezone();calendar.busy(now,now+timedelta(days=1))
        sheets.read_records()
        atomic(ACTIVATION,{'activated_at':datetime.now(timezone.utc).isoformat(),'resources':resources(c),
            'identities':'configured synthetic Patient A/B and synthetic doctor','real_patient_enabled':False})
        if STORAGE.exists():STORAGE.unlink()
        print('Google mode is on: bookings go to the clinic Google Calendar and register. Restart both assistants.');return
    if a.operation=='synthetic-google-test':
        # Optional maintainer end-to-end check: books and cancels one synthetic event,
        # each write approved in the on-screen dialog. Not part of doctor setup.
        from live import macos_approver
        from verification import verify_google
        report=verify_google(calendar,sheets,c,a.start or next_test_slot(calendar,c),macos_approver(lambda:c['timezone']))
        print(json.dumps(report,indent=2))
        if not report.get('passed'):sys.exit(1)

def next_test_slot(calendar,c):
    """Latest free slot on the next open clinic day, so the test disturbs nobody."""
    from datetime import datetime,timedelta
    from zoneinfo import ZoneInfo
    from core import Service,Identity
    finder=Service(Identity('synthetic-slot-finder','patient',c['clinic_id'],'synthetic',True),calendar,None,c)
    today=datetime.now(ZoneInfo(c['timezone'])).date()
    for n in range(1,15):
        day=today+timedelta(days=n)
        if day.weekday() in c['working_days'] and (found:=finder.slots(day.isoformat())):return found[-1]
    raise AdminError('No free clinic slot in the next two weeks for the one-time test booking')

SETTINGS=('clinic_name','timezone','working_days','opening','closing','breaks','duration_minutes','buffer_minutes','address','contact','confirmation_policy','cancellation_policy','booking_mode','daily_caps','queue_minutes')

def clinic_settings(pairs):
    """Validated non-secret clinic details, saved for both Google and on-this-computer storage."""
    from server import LOCAL_STATE
    path=ROOT/'config'/'google-clinic.json'
    c=json.loads(path.read_text()) if path.exists() else dict(DEFAULT)
    for pair in pairs:
        field,sep,raw=pair.partition('=')
        if not sep or field not in SETTINGS:raise AdminError('Use FIELD=VALUE with one of: '+', '.join(SETTINGS))
        try:c[field]=json.loads(raw) if field in ('working_days','breaks','duration_minutes','buffer_minutes','daily_caps','queue_minutes') else raw
        except ValueError:raise AdminError(field+' needs a JSON value, e.g. working_days=[0,1,2,3,4] breaks=[["13:00","14:00"]]') from None
    c=validate_config(c);atomic(path,c)
    if LOCAL_STATE.exists():
        with lock(LOCAL_STATE.with_suffix('.lock')):
            state=json.loads(LOCAL_STATE.read_text());state['config']=validate_config(state['config']|{k:c[k] for k in SETTINGS});atomic(LOCAL_STATE,state)
    print(json.dumps({k:c[k] for k in SETTINGS},indent=2))

def use_laptop():
    """Keep bookings in a file on this computer. Existing local bookings are never reset."""
    from server import LOCAL_STATE
    from live import ACTIVATION,STORAGE
    path=ROOT/'config'/'google-clinic.json'
    c=json.loads(path.read_text()) if path.exists() else dict(DEFAULT)
    if not LOCAL_STATE.exists():
        config=validate_config(dict(DEFAULT)|{k:c[k] for k in SETTINGS if k in c})
        atomic(LOCAL_STATE,{'config':config,'events':{},'records':{},'fail_next':False,'last_sync':'never'})
    if ACTIVATION.exists():ACTIVATION.unlink()  # Google sign-in is kept; run activate to switch back
    atomic(STORAGE,{'storage':'laptop'})
    print('Bookings are now kept on this computer. Restart both assistants.')

def sheet_from_url(raw):
    parsed=urlparse(raw.strip());parts=parsed.path.split('/')
    if parsed.scheme!='https' or parsed.netloc not in ('docs.google.com','www.docs.google.com') or len(parts)<4 or parts[1]!='spreadsheets' or parts[2]!='d':
        raise AdminError('Use a Google Sheets URL such as https://docs.google.com/spreadsheets/d/…/edit')
    if not parts[3] or not all(ch.isalnum() or ch in '_-' for ch in parts[3]):raise AdminError('The Google Sheets URL has an invalid spreadsheet ID')
    return parts[3]

def google_sign_in(client):
    """(credentials, newly_authorized). Reuses a working Keychain sign-in before asking for consent."""
    from google_adapter import credentials,authorize,list_calendars
    if client is None:
        try:
            creds=credentials();list_calendars(creds);return creds,False
        except Exception:
            if not sys.stdin.isatty():raise AdminError('No working saved Google sign-in. Provide --client with the Desktop OAuth client JSON path to sign in.') from None
            client=Path(input('Path to downloaded Desktop OAuth client JSON (outside this package): ').strip())
    client=client.expanduser().resolve()
    if not client.is_file():raise AdminError('Desktop OAuth client JSON path does not exist')
    try:client.relative_to(ROOT.resolve())
    except ValueError:pass
    else:raise AdminError('Keep the Desktop OAuth client JSON outside this package')
    print('A browser will open. Sign in with the clinic Google account and allow Calendar and Sheets access.')
    return authorize(client),True

def status():
    """Plain readiness summary for the setup assistant. No IDs, tokens or event text."""
    config_path=ROOT/'config'/'google-clinic.json'
    out={'google_libraries_installed':(ROOT/'.venv'/'bin'/'python').is_file(),'clinic_settings_saved':config_path.exists()}
    c=validate_config(json.loads(config_path.read_text())) if config_path.exists() else dict(DEFAULT)
    from server import LOCAL_STATE
    from live import storage_choice
    if storage_choice()=='laptop' and LOCAL_STATE.exists():c=json.loads(LOCAL_STATE.read_text())['config']
    out['clinic']={k:c[k] for k in SETTINGS}
    # Shipped defaults are placeholders, not the doctor's answers: ask for these.
    out['details_to_ask']=[k for k in ('clinic_name','address','contact') if c[k]==DEFAULT[k]]+([] if out['clinic_settings_saved'] else ['timezone','working_days','opening','closing','breaks','duration_minutes','buffer_minutes'])
    runtime=ROOT/'config'/'runtime'
    out['assistant_app']=runtime.read_text().strip() if runtime.exists() else None
    out['calendar_and_register_chosen']=bool(c['calendar_id'] and c['spreadsheet_id'])
    try:
        from google_adapter import credentials,list_calendars
        creds=credentials();calendars=list_calendars(creds);out['google_signed_in']=True
    except Exception as e:out['google_signed_in']=False;out['google_sign_in_problem']=type(e).__name__
    if out['google_signed_in'] and out['calendar_and_register_chosen']:
        from google_adapter import Calendar,Sheets
        try:
            Calendar(creds,c['calendar_id']).verify();meta=Sheets(creds,c['spreadsheet_id']).verify()
            out['calendar_and_register_reachable']=True;out['register_name']=meta.get('properties',{}).get('title')
        except Exception as e:out['calendar_and_register_reachable']=False;out['reach_problem']=type(e).__name__
        out['calendar_name']=next((x.get('summary') for x in calendars if x.get('id')==c['calendar_id']),None)
    from live import live_state,storage_choice
    state=live_state();choice=storage_choice()
    if choice=='google':out['bookings_kept_in']='Google Calendar and Sheets' if state['active'] else 'Google, but BROKEN ('+state['reason']+'): every request fails until setup is fixed'
    elif choice=='laptop':out['bookings_kept_in']='this computer'
    else:out['bookings_kept_in']='not chosen yet (setup unfinished)'
    return out

def run():
    # Google libraries live in the package venv; re-exec there before importing them.
    from runtime_python import ensure_package_interpreter
    ensure_package_interpreter(ROOT)
    try:main()
    except Exception as e:
        # OAuth libraries may include HTTP bodies/credentials in exception text.
        if isinstance(e,AdminError):print(str(e),file=sys.stderr)
        else:print(type(e).__name__+': operation failed; no secrets displayed',file=sys.stderr)
        sys.exit(1)

if __name__=='__main__':run()
