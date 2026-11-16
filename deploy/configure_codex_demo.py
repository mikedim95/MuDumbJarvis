#!/usr/bin/env python3
"""Stage the explicitly authorized read-only CEO demo; never starts any task.

Uses the existing server Codex login, keeps prior objectives natively paused,
backs up private configuration, and leaves every employee paused. Dry run is
the default. Apply once, refresh the CEO runtime with the demo Compose overlay,
then perform the separately authorized HUD demo. No tokens are printed.
"""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

import yaml
import staffing

ROOT = staffing.ROOT
spec = importlib.util.spec_from_file_location('codex_demo_policy', ROOT / 'hermes-plugin/jarvis_readonly/inference_policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    env = staffing.settings(); board = staffing.Board(env)
    ceo_id = env['PAPERCLIP_CEO_AGENT_ID']; company = env['PAPERCLIP_COMPANY_ID']
    roster = board.api('GET', '/companies/' + company + '/agents')
    ceo = next(a for a in roster if a['id'] == ceo_id)
    if any(a.get('status') not in ('paused', 'terminated', 'pending_approval') for a in roster):
        raise RuntimeError('Employees must stay paused while staging this demo')
    if board.api('GET', '/companies/' + company + '/live-runs'):
        raise RuntimeError('A native execution remains active; no configuration changed')
    old_issues = board.api('GET', '/companies/' + company + '/issues?assigneeAgentId=' + ceo_id)
    roots = [i for i in old_issues if i.get('assigneeAgentId') == ceo_id and
             not i.get('parentId') and i.get('status') not in ('done', 'cancelled')]
    login = Path.home() / '.codex/auth.json'
    credentials = json.loads(login.read_text())
    if not credentials.get('tokens', {}).get('access_token'):
        raise RuntimeError('Existing server-side Codex login required')
    view = {'provider': 'openai-codex', 'model': 'gpt-6.1-sol', 'ceo_id': ceo_id,
            'old_objectives_to_keep_paused': [i['id'] for i in roots], 'apply': args.apply}
    if not args.apply:
        print(json.dumps(view)); return
    target = ROOT / 'deploy/codex-demo.env'
    if target.exists():
        raise RuntimeError('Demo already staged; use its recorded backup for rollback before reapplying')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = ROOT / '.runtime/backups/codex-demo' / stamp
    backup.mkdir(parents=True, mode=0o700)
    staffing.write_private(backup / 'agent.json', json.dumps(ceo))
    home = ROOT / '.runtime/hermes-ceo'
    for name in ('config.yaml', 'SOUL.md', 'auth.json'):
        if (home / name).exists():
            shutil.copy2(home / name, backup / name); (backup / name).chmod(0o600)
    holds = []
    for issue in roots:
        active = board.api('GET', '/issues/' + issue['id'] + '/tree-holds?status=active&mode=pause')
        if isinstance(active, dict):
            active = active.get('holds', [])
        if not active:
            board.api('POST', '/issues/' + issue['id'] + '/tree-control/preview', {'mode': 'pause'})
            active = [board.api('POST', '/issues/' + issue['id'] + '/tree-holds', {
                'mode': 'pause', 'reason': 'Preserve user-stopped objective during the separately authorized Codex demo',
                'releasePolicy': {'strategy': 'manual'}, 'metadata': {'source': 'codex-demo-isolation'}})]
        holds.append({'issue_id': issue['id'], 'holds': active})
    staffing.write_private(backup / 'pause-holds.json', json.dumps(holds))
    record = {'version': 2, 'company_id': company, 'agent_id': ceo_id,
        'provider': 'openai-codex', 'model': 'gpt-6.1-sol', 'endpoint': policy.CODEX_ENDPOINT,
        'context_length': 65536, 'inference_slots': 1, 'fallback_allowed': False,
        'user_authorized': True, 'source': 'operator_authorized_codex_demo',
        'authority_scope': 'ceo_readonly_demo', 'selected_at': stamp}
    record['signature'] = policy.signature(record, env['JARVIS_EXECUTION_PROOF_KEY'])
    policy.validate(record, company, env['JARVIS_EXECUTION_PROOF_KEY'])
    # Import via Hermes' own credential-store helper. Login travels over stdin,
    # never in argv, environment, output, frontend or repository content.
    imported = subprocess.run(['docker', 'exec', '-i', 'jarvis-hermes-ceo',
        '/opt/hermes/.venv/bin/python', '-c',
        'import sys,json; from hermes_cli.auth import _save_codex_tokens; a=json.load(sys.stdin); _save_codex_tokens(a["tokens"],a.get("last_refresh"))'],
        input=json.dumps(credentials), text=True, capture_output=True, timeout=30)
    if imported.returncode:
        raise RuntimeError('Hermes credential import failed; inspect private configuration')
    c = yaml.safe_load((home / 'config.yaml').read_text())
    c['model'] = {'provider': 'openai-codex', 'default': record['model'],
                  'base_url': policy.CODEX_ENDPOINT, 'context_length': 65536}
    c.pop('providers', None)
    c['fallback_models'] = []
    staffing.write_private(home / 'config.yaml', yaml.safe_dump(c, sort_keys=False))
    scope = ('\n\nAUTHORIZED CODEX DEMO: The user explicitly selected Codex cloud inference for this demo. '
        'This supersedes the local-inference-only instruction for this CEO only. '
        'Use the actual tools to read Paperclip context, record decision=self with paperclip_ceo action=plan, '
        'and publish the requested concise internal report with publish_artifact. '
        'Do not hire, delegate, request approvals, access host files, use external actions or resume prior tasks. '
        'Keep prior stopped objectives paused. Finish the current new objective with actual findings and limits.\n')
    staffing.write_private(home / 'SOUL.md', (home / 'SOUL.md').read_text() + scope)
    meta = ceo.get('metadata') or {}; jarvis = meta.get('jarvis') or {}
    history = list(jarvis.get('inference_configuration_history') or [])
    if jarvis.get('inference_configuration'):
        history.append(jarvis['inference_configuration'])
    board.api('PATCH', '/agents/' + ceo_id, {
        'metadata': {**meta, 'jarvis': {**jarvis, 'inference_configuration': record,
                      'inference_configuration_history': history}},
        'adapterConfig': {**ceo['adapterConfig'], 'instructions': ceo['adapterConfig']['instructions'] + scope}})
    staffing.write_private(target, 'JARVIS_CODEX_DEMO_MODEL=gpt-6.1-sol\nJARVIS_CODEX_DEMO_CONFIGURATION=' +
        json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n')
    view.update(backup=str(backup.relative_to(ROOT)), employees_left_paused=True,
                native_holds_preserve_old_objectives=True, credentials_server_side=True)
    staffing.write_private(backup / 'receipt.json', json.dumps(view, indent=2))
    print(json.dumps(view))


if __name__ == '__main__':
    main()
