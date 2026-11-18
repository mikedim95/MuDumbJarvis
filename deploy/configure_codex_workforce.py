#!/usr/bin/env python3
"""Stage the human-authorized JARVIS CEO and four Codex specialists.

Dry run by default. Apply keeps all selected employees paused; the operator
must recreate, provision and verify their runtimes before resuming new work.
Old task holds are never released. Native hire approvals retain human/operator
attribution; this script never claims that a model requested the initial team.
"""
import argparse
import datetime
import fcntl
import json
from pathlib import Path
import shutil
import subprocess

import yaml
import staffing

TEAM = {'research': 'JARVIS Research', 'software_development': 'JARVIS Software',
        'system_administration': 'JARVIS Systems', 'security_analysis': 'JARVIS Security'}
OLD_ROOTS = ('f79972eb-c989-4845-bafa-7bd4e11a0eef',
    '48560754-910f-4521-b5c9-ad4078efef24', 'eeb52003-acef-4a34-98cf-45ffe585919e')
AUTHORIZATION_NOTE = staffing.WORKFORCE_HIRING_REASON


def profile_of(agent):
    return ((agent.get('metadata') or {}).get('jarvis') or {}).get('profile')


def choose_team(roster, ceo_id):
    selected = {}
    for profile in TEAM:
        matches = [a for a in roster if a.get('reportsTo') == ceo_id and profile_of(a) == profile
            and a.get('status') != 'terminated']
        if len(matches) > 1:
            raise ValueError('Review duplicate native employees for capability: ' + profile)
        selected[profile] = matches[0] if matches else None
    return selected


def bootstrap_hire_body(company, ceo_id, profile):
    item = staffing.registry.profile(profile)
    body = staffing.registry.hire_body({'company': company, 'issue': staffing.WORKFORCE_AUTHORIZATION},
        {'id': ceo_id}, profile, TEAM[profile], AUTHORIZATION_NOTE)
    body.pop('sourceIssueId', None)
    meta = body['metadata']['jarvis']; meta.pop('source_issue_id', None)
    meta.update(origin='operator_authorized_workforce',
        bootstrap_request=staffing.WORKFORCE_AUTHORIZATION,
        human_authorization=AUTHORIZATION_NOTE)
    return body


def migrate_profile_auth(path):
    """Borrow the shared grant; never leave a stale profile-owned rotating copy."""
    if not path.exists():
        return
    data = json.loads(path.read_text())
    for section in ('providers', 'credential_pool'):
        if isinstance(data.get(section), dict):
            data[section].pop('openai-codex', None)
    staffing.write_private(path, json.dumps(data, indent=2) + '\n')


def shared_credentials(root):
    shared = root / '.runtime/codex-shared'; shared.mkdir(mode=0o700, exist_ok=True)
    if shared.is_symlink():
        raise ValueError('Shared credentials directory must not be a symlink')
    if not (shared / 'auth.json').exists():
        login = Path.home() / '.codex/auth.json'; original = login.read_bytes()
        credentials = json.loads(original)
        if not credentials.get('tokens', {}).get('access_token'):
            raise ValueError('Existing server-side Codex login is required')
        code = ('import sys,json; from hermes_cli.auth import _save_codex_tokens,resolve_codex_runtime_credentials; '
            'a=json.load(sys.stdin); _save_codex_tokens(a["tokens"],a.get("last_refresh")); '
            'c=resolve_codex_runtime_credentials(read_only=True); '
            'assert c["base_url"].startswith("https://chatgpt.com/backend-api/codex"); '
            'print("shared_credential_import_verified")')
        result = subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none', '--user', '1000:1000',
            '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
            '--tmpfs', '/tmp:size=16m', '-e', 'HERMES_HOME=/opt/jarvis-codex',
            '-e', 'PYTHONDONTWRITEBYTECODE=1', '-v', str(shared) + ':/opt/jarvis-codex',
            '--entrypoint', '/opt/hermes/.venv/bin/python', staffing.HERMES_IMAGE, '-c', code],
            input=json.dumps(credentials), text=True, capture_output=True, timeout=40)
        if result.returncode or 'shared_credential_import_verified' not in result.stdout:
            raise RuntimeError('Shared Codex credential import failed; no credential output is published')
        if login.read_bytes() != original:
            raise RuntimeError('The source login unexpectedly changed')
    (shared / 'auth.json').chmod(0o600)
    # Empty mount targets only. No sibling profile content is placed here.
    for profile in ('ceo', 'chat', 'employee'):
        (shared / 'profiles' / profile).mkdir(parents=True, exist_ok=True)
    lock = shared / 'inference.lock'
    if not lock.exists():
        staffing.write_private(lock, '')


def stage_record(board, agent, item=None):
    record = staffing.workforce_record(agent, board.env, item)
    metadata = agent.get('metadata') or {}; meta = metadata.get('jarvis') or {}
    history = list(meta.get('inference_configuration_history') or [])
    if meta.get('inference_configuration') and meta['inference_configuration'] != record:
        history.append(meta['inference_configuration'])
    update = {**meta, 'inference_configuration': record, 'inference_configuration_history': history}
    if item:
        update.update(provisioned=False, operator_inference_upgrade_pending=True,
            suppress_historical_readiness_notice=True)
    patch = {'metadata': {**metadata, 'jarvis': update}}
    if item:
        patch.update(name=TEAM[item['id']], title=item['name'])
    else:
        instructions = (staffing.ROOT / 'deploy/JARVIS_CEO_POLICY.md').read_text()
        patch.update(name='JARVIS', title='Chief Executive Officer',
            capabilities='Plan objectives, select scoped specialists, delegate native Paperclip work, review evidence and report to the human. Future hires and sensitive actions require human approval.',
            adapterConfig={**agent['adapterConfig'], 'instructions': instructions})
    board.api('PATCH', '/agents/' + agent['id'], patch)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true'); args = parser.parse_args()
    root = staffing.ROOT; env = staffing.settings(); board = staffing.Board(env)
    company = env['PAPERCLIP_COMPANY_ID']; ceo_id = env['PAPERCLIP_CEO_AGENT_ID']
    roster = board.api('GET', '/companies/' + company + '/agents')
    ceo = next(a for a in roster if a['id'] == ceo_id and a['role'] == 'ceo')
    team = choose_team(roster, ceo_id)
    view = {'apply': args.apply, 'ceo_id': ceo_id, 'ceo_name': 'JARVIS',
        'provider': 'openai-codex', 'model': 'gpt-6.1-sol', 'shared_inference_slots': 1,
        'reuse': {p: a['id'] for p, a in team.items() if a},
        'missing_profiles': [p for p, a in team.items() if not a],
        'future_hiring_requires_human_approval': True, 'old_task_holds_released': False}
    if not args.apply:
        print(json.dumps(view)); return
    # Keep the same operator lock as staffing.py through this apply invocation.
    # The local handle is closed when main exits, including exceptional exits.
    operator_lock = (root / '.runtime/employee-runtime.lock').open('a')
    fcntl.flock(operator_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    company_state = board.api('GET', '/companies/' + company)
    if not company_state.get('requireBoardApprovalForNewAgents'):
        raise ValueError('Native human hiring approval must remain enabled')
    if board.api('GET', '/companies/' + company + '/live-runs'):
        raise ValueError('Live or queued native executions remain; no configuration changed')
    for iid in OLD_ROOTS:
        holds = board.api('GET', '/issues/' + iid + '/tree-holds?status=active&mode=pause')
        if not (holds.get('holds', []) if isinstance(holds, dict) else holds):
            raise ValueError('Original stopped objective requires its existing manual native hold')
    state_path = root / '.runtime/codex-workforce/setup.json'
    prior = json.loads(state_path.read_text()) if state_path.exists() else {}
    if prior.get('state') == 'staged':
        for profile, agent in team.items():
            if not agent:
                raise ValueError('Staged workforce lost an approved employee')
            staffing.selected_inference(agent, staffing.registry.profile(profile), env)
        print(json.dumps({**view, 'already_staged': True, 'backup': prior['backup']})); return
    timer = subprocess.run(['systemctl', '--user', 'is-active', 'jarvis-employee-runtimes.timer'],
        text=True, capture_output=True)
    if timer.stdout.strip() != 'inactive':
        raise ValueError('Stop the runtime reconciler timer while staging')
    direct = staffing.inspect('container', 'jarvis-hermes')
    if direct and direct['State']['Running']:
        raise ValueError('Stop only the direct-chat runtime during shared credential migration')
    if not prior:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = root / '.runtime/backups/codex-workforce' / stamp
        backup.mkdir(parents=True, mode=0o700)
        staffing.write_private(backup / 'agents.json', json.dumps(roster))
        staffing.write_private(backup / 'deploy.env', (root / 'deploy/.env').read_text())
        homes = [root / '.runtime/hermes', root / '.runtime/hermes-ceo',
                 *(root / '.runtime/employees' / a['id'] for a in team.values() if a)]
        for home in homes:
            directory = backup / home.name; directory.mkdir(mode=0o700)
            for name in ('config.yaml', 'SOUL.md', 'auth.json', 'runtime.env'):
                if (home / name).exists():
                    shutil.copy2(home / name, directory / name); (directory / name).chmod(0o600)
        prior = {'state': 'staging', 'backup': str(backup.relative_to(root)), 'hires': {}}
        staffing.write_private(state_path, json.dumps(prior, indent=2))
    for agent in [ceo, *(a for a in team.values() if a)]:
        board.api('POST', '/agents/' + agent['id'] + '/pause', {})
    shared_credentials(root)
    for profile, agent in team.items():
        if not agent:
            hired = board.api('POST', '/companies/' + company + '/agent-hires',
                bootstrap_hire_body(company, ceo_id, profile))
            agent = hired['agent']; approval = hired['approval']
            prior['hires'][profile] = {'agent_id': agent['id'], 'approval_id': approval['id']}
            staffing.write_private(state_path, json.dumps(prior, indent=2))
            team[profile] = agent
        meta = (agent.get('metadata') or {}).get('jarvis') or {}
        if agent.get('status') == 'pending_approval':
            if (meta.get('origin') != 'operator_authorized_workforce'
                    or (meta.get('bootstrap_request') != staffing.WORKFORCE_AUTHORIZATION and
                        meta.get('hiring_reason') != AUTHORIZATION_NOTE)):
                raise ValueError('Existing pending hire has no authorization from this human request')
            approvals = board.api('GET', '/companies/' + company + '/approvals')
            approval = next(a for a in approvals if (a.get('payload') or {}).get('agentId') == agent['id']
                and a['type'] == 'hire_agent' and a['status'] == 'pending')
            board.api('POST', '/approvals/' + approval['id'] + '/approve', {'decisionNote': AUTHORIZATION_NOTE})
            agent = board.api('GET', '/agents/' + agent['id']); team[profile] = agent
        board.api('POST', '/agents/' + agent['id'] + '/pause', {})
        stage_record(board, agent, staffing.registry.profile(profile))
    ceo_record = stage_record(board, ceo)
    for home in (root / '.runtime/hermes', root / '.runtime/hermes-ceo',
                 *(root / '.runtime/employees' / a['id'] for a in team.values())):
        home.mkdir(parents=True, exist_ok=True)
        migrate_profile_auth(home / 'auth.json')
        if home.name in ('hermes', 'hermes-ceo'):
            config = staffing.codex_config(yaml.safe_load((home / 'config.yaml').read_text()))
            if home.name == 'hermes-ceo':
                config['agent']['max_turns'] = 24
                staffing.write_private(home / 'SOUL.md', (root / 'deploy/JARVIS_CEO_POLICY.md').read_text())
            staffing.write_private(home / 'config.yaml', yaml.safe_dump(config, sort_keys=False))
    staffing.write_private(root / 'deploy/codex-workforce.env',
        'JARVIS_CODEX_CEO_MODEL=gpt-6.1-sol\nJARVIS_CODEX_CEO_CONFIGURATION=' +
        json.dumps(ceo_record, sort_keys=True, separators=(',', ':')) + '\n')
    prior.update(state='staged', ceo_id=ceo_id, team={p: a['id'] for p, a in team.items()})
    staffing.write_private(state_path, json.dumps(prior, indent=2))
    print(json.dumps({**view, 'staged': True, 'backup': prior['backup'], 'team': prior['team'],
        'employees_left_paused': True, 'next': 'Recreate with workforce overlay; provision and verify each runtime; only then resume new work.'}))


if __name__ == '__main__':
    main()
