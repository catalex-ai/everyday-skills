"""Native PreToolUse allowlist for Codex and Claude. Never a skill boundary."""
import argparse,json,sys
from core import PATIENT,DOCTOR

def decide(role,event):
    names={'mcp__clinic__'+x for x in (PATIENT if role=='patient' else DOCTOR if role=='doctor' else set())}
    if event.get('tool_name')=='Skill':
        return event.get('tool_input',{}).get('skill')==('appointments' if role=='patient' else 'clinic')
    return event.get('tool_name') in names

def main():
    p=argparse.ArgumentParser();p.add_argument('--role',choices=['patient','doctor'],required=True);a=p.parse_args()
    try:
        event=json.load(sys.stdin)
        if isinstance(event,dict) and decide(a.role,event):return
    except Exception:pass
    print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':'Clinic session permits only its authenticated role-specific clinic tools.'}}))
    sys.exit(2)

if __name__=='__main__':main()
