"""Audit native Codex/Claude sessions. This is a test tool, not a launcher."""
import json,subprocess,sys,os,time,tempfile,threading,queue
from pathlib import Path
from datetime import datetime,timezone
from core import ROOT,PATIENT,DOCTOR,atomic

def environment(role,root=ROOT):
    env={k:os.environ[k] for k in ('HOME','USER','LOGNAME','PATH','SHELL','TERM','LANG','LC_ALL','TMPDIR') if k in os.environ}
    env['CODEX_HOME']=str(root/(role+'-agent')/'.codex')
    env['CLAUDE_CODE_SKIP_PROMPT_HISTORY']='1'
    return env

def inventory(stream,role):
    messages=[]
    for line in stream.splitlines():
        try:messages.append(json.loads(line))
        except ValueError:continue
    init=next((m for m in messages if m.get('type')=='system' and m.get('subtype')=='init'),None)
    if init is None:return {'status':'unverified','reason':'No actual CLI initialization inventory received'}
    actual=set(init.get('tools',[]));expected={'mcp__clinic__'+t for t in (PATIENT if role=='patient' else DOCTOR)}|{'Skill'}
    extra=actual-expected-{'EndConversation'};missing=expected-actual
    calls=[];results=[]
    for message in messages:
        for block in message.get('message',{}).get('content',[]):
            if isinstance(block,dict) and block.get('type')=='tool_use':calls.append(block.get('name'))
            if isinstance(block,dict) and block.get('type')=='tool_result':results.append(bool(block.get('is_error',False)))
    role_skill='clinic-role:'+('appointments' if role=='patient' else 'clinic')
    skill_discovered=role_skill in init.get('skills',[])
    clinic_call=any(name and name.startswith('mcp__clinic__') for name in calls)
    connected=bool(init.get('mcp_servers')) and all(s.get('status')=='connected' for s in init['mcp_servers'])
    return {'status':'passed' if not extra and not missing and connected and clinic_call and skill_discovered and not any(results) else 'failed','role_skill_discovered':skill_discovered,'native_skills':init.get('skills',[]),'actual_tools':sorted(actual),'unexpected_tools':sorted(extra),'missing_tools':sorted(missing),'mcp_connected':connected,'observed_tool_calls':calls,'clinic_call_observed':clinic_call,'tool_error_observed':any(results)}

class RPC:
    def __init__(self,role,root=ROOT):
        self.process=subprocess.Popen(['codex','--dangerously-bypass-hook-trust','app-server','--stdio','--strict-config'],cwd=root/(role+'-agent'),env=environment(role,root),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
        self.messages=queue.Queue();self.ident=0
        def reader():
            for line in self.process.stdout:self.messages.put(json.loads(line))
            self.messages.put(None)
        threading.Thread(target=reader,daemon=True).start()
    def call(self,method,params,timeout=30):
        self.ident+=1;ident=self.ident
        self.process.stdin.write(json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params})+'\n');self.process.stdin.flush()
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:msg=self.messages.get(timeout=max(.01,end-time.monotonic()))
            except queue.Empty:break
            if msg is None:raise RuntimeError('Native server exited')
            if msg.get('id')==ident:
                if 'error' in msg:raise RuntimeError('Native RPC rejected '+method)
                return msg['result']
        raise TimeoutError('Native RPC did not complete')
    def close(self):
        self.process.terminate()
        try:self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait()

def codex_audit(role):
    rpc=RPC(role);folder=ROOT/(role+'-agent')
    try:
        rpc.call('initialize',{'clientInfo':{'name':'doctor-assistant-audit','version':'0.2.0'},'capabilities':{'experimentalApi':True}})
        rpc.process.stdin.write('{"method":"initialized"}\n');rpc.process.stdin.flush()
        config=rpc.call('config/read',{'includeLayers':False,'cwd':str(folder)})['config']
        thread=rpc.call('thread/start',{'cwd':str(folder),'ephemeral':True})
        servers=rpc.call('mcpServerStatus/list',{'threadId':thread['thread']['id'],'detail':'toolsAndAuthOnly','limit':100})
        skills=rpc.call('skills/list',{'cwds':[str(folder)],'forceReload':True})
        expected=PATIENT if role=='patient' else DOCTOR
        active=servers['data'];names={s['name'] for s in active};tools=set(active[0].get('tools',{})) if len(active)==1 else set()
        disabled=('shell_tool','apps','plugins','browser_use','browser_use_external','computer_use','image_generation','in_app_browser','multi_agent','multi_agent_v2','view_image','request_permissions_tool')
        feature_check=all(config.get('features',{}).get(k) is False for k in disabled)
        actual_profile=thread.get('activePermissionProfile');approval=thread.get('approvalPolicy')
        # Controlled OS probes use synthetic canaries, never credential files.
        canary=ROOT/'config'/'audit-canary.txt'
        if canary.exists():raise RuntimeError('Probe path already exists; refusing overwrite')
        canary.write_text('SYNTHETIC_DENIED_READ_CANARY')
        write=folder/'runtime-denial-probe.txt'
        if write.exists():raise RuntimeError('Probe path already exists; refusing overwrite')
        def probe(args):
            run=subprocess.run(['codex','sandbox','-P','clinic','-C',str(folder),*args],cwd=folder,env=environment(role),capture_output=True,text=True,timeout=10)
            return {'exit_code':run.returncode,'denied':run.returncode!=0,'canary_leaked':'SYNTHETIC_DENIED_READ_CANARY' in run.stdout}
        read=probe(['/bin/cat',str(canary)]);modify=probe(['/usr/bin/touch',str(write)])
        baseline=subprocess.run(['/usr/bin/curl','--noproxy','*','--max-time','5','--output','/dev/null','https://example.com'],capture_output=True,text=True,timeout=8)
        network=probe(['/usr/bin/curl','--noproxy','*','--max-time','3','https://example.com'])
        network['baseline_access_verified']=baseline.returncode==0
        network['denied']=network['denied'] and network['baseline_access_verified']
        write_absent=not write.exists()
        canary.unlink()
        if write.exists():write.unlink() # remove only our known harmless probe
        paths=[]
        for entry in skills.get('data',[]):
            for skill in entry.get('skills',[]):
                if str(folder/'.agents'/'skills') in str(skill.get('path','')):paths.append(Path(skill['path']).parent.name)
        expected_skill='appointments' if role=='patient' else 'clinic'
        passed=names=={'clinic'} and tools==expected and feature_check and approval=='never' and actual_profile and read['denied'] and not read['canary_leaked'] and modify['denied'] and write_absent and network['denied'] and expected_skill in paths
        return {'status':'passed' if passed else 'failed','mcp_servers':sorted(names),'actual_clinic_tools':sorted(tools),'effective_disabled_features':{k:config.get('features',{}).get(k) for k in disabled},'active_permission_profile':actual_profile,'approval_policy':approval,'instruction_sources':thread.get('instructionSources',[]),'native_skills':paths,'filesystem_read_probe':read,'filesystem_write_probe':modify,'write_probe_file_absent':write_absent,'network_probe':network,'builtin_tool_inventory':{'status':'unverified','reason':'Native MCP inventory and effective config verified; complete built-in model schema not exposed by this audit'},'config_api_verified':True}
    finally:rpc.close()

def claude_audit(role):
    folder=ROOT/(role+'-agent')
    command=['claude','--restricted','--tools','Skill','--strict-mcp-config','--mcp-config','.mcp.json','--setting-sources','','--plugin-dir','.claude','--append-system-prompt-file','AGENTS.md','--settings','.claude/settings.json','--permission-mode','dontAsk','--no-chrome','-p','--output-format','stream-json','--verbose','Invoke the clinic-role:'+('appointments' if role=='patient' else 'clinic')+' skill and show '+('my appointments' if role=='patient' else 'the clinic connection status')+'. Do not modify appointments or files.']
    run=subprocess.run(command,cwd=folder,env=environment(role),capture_output=True,text=True,timeout=55)
    result=inventory(run.stdout,role);result['exit_code']=run.returncode
    if run.returncode:result['status']='unverified'
    return result

def audit(runtime='both'):
    result={'time':datetime.now(timezone.utc).isoformat(),'version':'0.2.0','mode':'synthetic-only','runtimes':{},'real_patient_enabled':False,'os_credential_boundary':'unverified: same-UID helper and Keychain ACLs not isolated','gateway_identity':'unverified: no trusted live identity broker configured','human_confirmation_provenance':'unverified: model-visible tokens are not proof of consent','google_live_verification':'unverified: no consented Google integration performed'}
    for name,fn in [('codex',codex_audit),('claude',claude_audit)]:
        if runtime not in ('both',name):continue
        value={'sessions':{}}
        try:value['cli_version']=subprocess.run([name,'--version'],capture_output=True,text=True,check=True).stdout.strip()
        except Exception:value['cli_version']='unavailable'
        for role in ('patient','doctor'):
            try:value['sessions'][role]=fn(role)
            except Exception as e:value['sessions'][role]={'status':'unverified','reason':type(e).__name__+' during native runtime probe'}
        result['runtimes'][name]=value
    atomic(ROOT/'config'/'audit-report.json',result);return result

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--runtime',choices=['codex','claude','both'],default='both');a=p.parse_args()
    print(json.dumps(audit(a.runtime),indent=2))
