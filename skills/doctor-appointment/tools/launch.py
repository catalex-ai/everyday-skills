"""Restricted CLI session launcher, not an installer. No caller-supplied CLI flags."""
import json,os,shutil,subprocess,sys
from pathlib import Path
from core import ROOT,PATIENT,DOCTOR

def command(role,patient='patient-a',print_prompt=None):
    if role not in ('patient','doctor') or patient not in ('patient-a','patient-b'):raise ValueError('Invalid role/identity')
    cli=shutil.which('claude')
    if not cli:raise RuntimeError('Claude Code required')
    helptext=subprocess.run([cli,'--help'],capture_output=True,text=True,check=True).stdout
    for flag in ('--restricted','--tools','--strict-mcp-config','--setting-sources','--disable-slash-commands'):
        if flag not in helptext:raise RuntimeError('Installed Claude Code lacks required restriction: '+flag)
    config={'mcpServers':{'clinic':{'command':sys.executable,'args':[str(ROOT/'tools'/'server.py'),'--role',role,'--patient',patient],'env':{'PYTHONPATH':str(ROOT/'tools')}}}}
    tools=sorted(PATIENT if role=='patient' else DOCTOR)
    settings={'disableAllHooks':True,'permissions':{'defaultMode':'dontAsk','disableBypassPermissionsMode':'disable','allow':['mcp__clinic__'+t for t in tools]},'sandbox':{'enabled':True,'allowUnsandboxedCommands':False,'failIfUnavailable':True}}
    # Restricted + built-in removal is the primary control. The Bash sandbox
    # does not contain the trusted MCP process, which is deliberately narrow.
    result=[cli,'--restricted','--tools','','--strict-mcp-config','--mcp-config',json.dumps(config),
       '--setting-sources','','--settings',json.dumps(settings),'--permission-mode','dontAsk','--no-chrome',
       '--disable-slash-commands','--system-prompt',(ROOT/(role+'-agent')/'CLAUDE.md').read_text()]
    if print_prompt:result+=['-p','--output-format','stream-json','--verbose',print_prompt]
    return result

def environment():
    # Do not pass Google or gateway secrets from a developer shell to Claude/MCP.
    allowed=('HOME','USER','LOGNAME','PATH','SHELL','TERM','LANG','LC_ALL','TMPDIR','COLORTERM')
    e={k:os.environ[k] for k in allowed if k in os.environ}
    e['CLAUDE_CODE_SKIP_PROMPT_HISTORY']='1';e['ENABLE_TOOL_SEARCH']='false'
    return e

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--role',choices=['patient','doctor'],required=True);p.add_argument('--patient',choices=['patient-a','patient-b'],default='patient-a')
    a=p.parse_args();os.chdir(ROOT/(a.role+'-agent'))
    cmd=command(a.role,a.patient)
    os.execvpe(cmd[0],cmd,environment())
