"""Where bookings live, and the trusted Google runtime.

The storage choice is made only by the setup helper (admin.py), never by the
patient/doctor sessions. Google mode is entered by `admin.py activate`, which
verifies the stored sign-in can read the chosen calendar and register and then
writes an activation record bound to those resources. Once that record exists,
a resource mismatch or credential failure makes every tool call fail closed; it
never falls back to bookings kept on this computer.
"""
import json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from core import ROOT, Service, Identity, validate_config, stamp, lock

CONFIG = ROOT/'config'/'google-clinic.json'
ACTIVATION = ROOT/'config'/'live-activation.json'
STORAGE = ROOT/'config'/'storage.json'
LIVE_LOCK = ROOT/'config'/'live.lock'
DIALOG_SECONDS = 90

def load_config():
    if not CONFIG.exists(): raise PermissionError('Google is not configured; run google-setup in a human terminal')
    c = validate_config(json.loads(CONFIG.read_text()))
    if not c['calendar_id'] or not c['spreadsheet_id']: raise PermissionError('Google calendar/register not selected; run google-setup')
    return c

def resources(c):
    return {k: c[k] for k in ('clinic_id', 'calendar_id', 'spreadsheet_id')}

def read_json(path):
    if not path.exists():return None
    value=json.loads(path.read_text())
    if not isinstance(value,dict):raise ValueError('Record must be an object')
    return value

def live_state():
    """{'required': activation exists, 'active': all bindings hold, 'reason': ...}"""
    try:
        activation = read_json(ACTIVATION)
    except Exception as e:
        return {'required': True, 'active': False, 'reason': 'Activation record unavailable or invalid: ' + type(e).__name__}
    if activation is None:
        return {'required': False, 'active': False, 'reason': 'Google mode not set up'}
    try:
        if not isinstance(activation, dict):raise ValueError('Invalid activation record')
        c = load_config()
        if activation.get('resources') != resources(c): return {'required': True, 'active': False, 'reason': 'Clinic calendar or register changed since setup; run setup again'}
        if activation.get('real_patient_enabled') is not False: return {'required': True, 'active': False, 'reason': 'Invalid activation record'}
    except PermissionError as e:
        return {'required': True, 'active': False, 'reason': str(e)}
    except Exception as e:
        return {'required': True, 'active': False, 'reason': 'Activation verification failed: ' + type(e).__name__}
    return {'required': True, 'active': True, 'reason': 'Google mode active', 'activated_at': activation.get('activated_at')}

def storage_choice():
    """'google' when activated, 'laptop' when chosen in setup, else None (not set up)."""
    if ACTIVATION.exists(): return 'google'
    try: return 'laptop' if read_json(STORAGE).get('storage') == 'laptop' else None
    except Exception: return None

def describe(action, payload, tz):
    """Human-readable dialog text built only from trusted, validated fields."""
    def when(value):
        try: return stamp(value).astimezone(ZoneInfo(tz)).strftime('%a %d %b %Y, %H:%M') + ' (' + tz + ')'
        except Exception: return str(value)[:60]
    lines = ['Doctor Assistant wants to change the clinic Google Calendar.', '', 'Action: ' + action.upper()]
    if action == 'book':
        lines += ['Patient: ' + str(payload.get('owner'))[:60], 'Start: ' + when(payload.get('start')), 'End: ' + when(payload.get('end'))]
    elif action in ('cancel', 'reschedule'):
        lines += ['Appointment: ' + str(payload.get('appointment_id'))[:12] + '…']
        if payload.get('start'): lines += ['New start: ' + when(payload['start'])]
    elif action in ('block', 'unblock'):
        lines += ['From: ' + when(payload.get('start')), 'To: ' + when(payload.get('end'))]
        if payload.get('conflicts'): lines += ['Overlapping appointments: ' + str(len(payload['conflicts']))]
    elif action == 'configure':
        keys = ('clinic_name', 'timezone', 'working_days', 'opening', 'closing', 'breaks', 'duration_minutes', 'buffer_minutes')
        lines += [k + ': ' + json.dumps(payload.get(k))[:80] for k in keys]
    lines += ['', 'Approve only if you asked for exactly this.']
    return '\n'.join(lines)[:1500]

def macos_approver(tz_source):
    """Out-of-band confirmation on this Mac's screen. Fails closed."""
    def approve(action, payload):
        if sys.platform != 'darwin' or not Path('/usr/bin/osascript').exists(): return False
        text = describe(action, payload, tz_source())
        # Text is passed as argv, never interpolated into AppleScript source.
        script = ['-e', 'on run argv',
                  '-e', f'display dialog (item 1 of argv) with title "Doctor Assistant approval" buttons {{"Deny", "Approve"}} default button "Deny" cancel button "Deny" with icon caution giving up after {DIALOG_SECONDS}',
                  '-e', 'end run']
        try:
            run = subprocess.run(['/usr/bin/osascript', *script, text], capture_output=True, text=True, timeout=DIALOG_SECONDS+15)
        except Exception:
            return False
        out = run.stdout.strip()
        return run.returncode == 0 and 'button returned:Approve' in out and 'gave up:true' not in out
    return approve

def google_clients(c):
    from google_adapter import credentials, Calendar, Sheets
    creds = credentials()
    return creds, Calendar(creds, c['calendar_id']), Sheets(creds, c['spreadsheet_id'])

class LiveRuntime:
    """Same role/identity surface as PracticeRuntime, backed by Google."""
    def __init__(self, role, patient='patient-a', approver=None):
        if role not in ('patient', 'doctor') or patient not in ('patient-a', 'patient-b'): raise ValueError('Invalid synthetic identity')
        state = live_state()
        if not state['active']: raise PermissionError('Live Google mode unavailable: ' + state['reason'])
        self.role = role
        c = load_config()
        try: _, calendar, sheets = google_clients(c)
        except Exception: raise PermissionError('Stored Google authorization unavailable or invalid; re-run google-setup in a human terminal') from None
        identity = Identity(patient if role == 'patient' else 'synthetic-doctor', role, c['clinic_id'], 'synthetic', True)
        self.service = Service(identity, calendar, sheets, c, config_path=CONFIG,
                               approver=approver or macos_approver(lambda: self.service.config['timezone']), synthetic_directory=True)
        from core import NoticeLog
        self.service.notices_seen = NoticeLog(ROOT/'config'/'notices-seen.json')
    def tools(self):
        from core import PATIENT, DOCTOR
        return sorted(PATIENT if self.role == 'patient' else DOCTOR)
    def call(self, name, args):
        state = live_state()
        if not state['active']: raise PermissionError('Live Google mode unavailable: ' + state['reason'])
        with lock(LIVE_LOCK):
            # Reload hours/policies another session may have changed; resources are immutable.
            c = load_config()
            if resources(c) != resources(self.service.config): raise PermissionError('Configured Google resources changed; restart after re-activation')
            self.service.config = c
            if name == 'doctor_verify_synthetic_appointment':
                raise PermissionError('This check is not available with Google; run admin.py synthetic-google-test from the setup terminal')
            result = self.service.call(name, args)
            if name == 'doctor_connection_status':
                result = result | {'mode': 'google', 'activated_at': state.get('activated_at')}
            return result | {'execution_mode': 'live-google', 'google_accessed': True}

class UnavailableRuntime:
    """Activation exists but cannot be honoured: refuse every call, never mock."""
    def __init__(self, role, reason):
        self.role, self.reason = role, reason
    def tools(self):
        from core import PATIENT, DOCTOR
        return sorted(PATIENT if self.role == 'patient' else DOCTOR)
    def call(self, name, args):
        raise PermissionError('Live Google mode unavailable: ' + self.reason + '. Nothing was read or changed.')
