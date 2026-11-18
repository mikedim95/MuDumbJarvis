#!/usr/bin/env python3
"""Operator model-only selection. Dry run by default; never hires or runs a task.

After --apply, selected employees remain paused until their owned runtimes are
refreshed and pass health/native-adapter checks. Keep the operator timer stopped
while applying this reviewed change. Historical capability approvals stay intact.
"""
import argparse
import datetime
import importlib.util
import json
import os
import re
from pathlib import Path
import secrets
import sys

import staffing
import select_ollama_profile as selector

ROOT = staffing.ROOT
spec = importlib.util.spec_from_file_location('inference_selection', ROOT / 'hermes-plugin/jarvis_readonly/inference_policy.py')
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    env = staffing.settings(); board = staffing.Board(env)
    selector.validate_model(args.model)
    shown = selector.ollama_json('/api/show', {'model': args.model})
    if re.findall(r'(?m)^\s*num_thread\s+(\d+)\s*$', shown.get('parameters', '')) != ['24']:
        raise ValueError('Reviewed 24-thread profile required')
    selected = next(m for m in selector.ollama_json('/api/tags')['models'] if m['name'] == args.model)
    record = {'version': 1, 'company_id': env['PAPERCLIP_COMPANY_ID'], 'provider': 'local_ollama',
        'model': args.model, 'model_digest': selected['digest'], 'inference_slots': 1,
        'cpu_threads': 24, 'context_length': 65536, 'source': 'operator_model_selection',
        'selected_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    old = json.loads(env['JARVIS_INFERENCE_CONFIGURATION']) if env.get('JARVIS_INFERENCE_CONFIGURATION') else None
    if old and old.get('model') == args.model and old.get('model_digest') == selected['digest']:
        record = policy.validate(old, env['PAPERCLIP_COMPANY_ID'], env['JARVIS_EXECUTION_PROOF_KEY'])
    else:
        record['signature'] = policy.signature(record, env['JARVIS_EXECUTION_PROOF_KEY'])
        policy.validate(record, env['PAPERCLIP_COMPANY_ID'], env['JARVIS_EXECUTION_PROOF_KEY'])
    roster = board.api('GET', '/companies/' + env['PAPERCLIP_COMPANY_ID'] + '/agents')
    active = [a for a in roster if a.get('status') not in ('terminated', 'pending_approval', 'paused') and
        (a['id'] == env['PAPERCLIP_CEO_AGENT_ID'] or ((a.get('metadata') or {}).get('jarvis') or {}).get('provisioned'))]
    view = {'selected_model': args.model, 'base_capability_templates_changed': False,
        'human_hiring_approvals_changed': False, 'shared_inference_slots': 1,
        'agents': [a['id'] for a in active], 'record': record, 'apply': args.apply}
    if not args.apply:
        print(json.dumps(view)); return
    if board.api('GET', '/companies/' + env['PAPERCLIP_COMPANY_ID'] + '/live-runs'):
        raise RuntimeError('Active/queued work remains; no configuration changed')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = ROOT / '.runtime/backups/phase14' / ('inference-' + stamp + '-' + secrets.token_hex(3))
    backup.mkdir(parents=True, mode=0o700)
    staffing.write_private(backup / 'deploy.env', (ROOT / 'deploy/.env').read_text())
    staffing.write_private(backup / 'agents.json', json.dumps([{'id':a['id'],'status':a['status'],'metadata':a.get('metadata')} for a in active]))
    for a in active:
        board.api('POST', '/agents/' + a['id'] + '/pause', {})
    if board.api('GET', '/companies/' + env['PAPERCLIP_COMPANY_ID'] + '/live-runs'):
        raise RuntimeError('Work raced the pause; employees stay paused for review')
    selector.select_profile(ROOT, args.model, apply=True)
    for a in active:
        metadata = a.get('metadata') or {}; meta = metadata.get('jarvis') or {}
        history = list(meta.get('inference_configuration_history') or [])
        if meta.get('inference_configuration') and meta['inference_configuration'] != record:
            history.append(meta['inference_configuration'])
        upgrade = {'inference_configuration': record, 'inference_configuration_history': history[-10:]}
        if meta.get('managed'):
            upgrade.update(provisioned=False, operator_inference_upgrade_pending=True)
        board.api('PATCH', '/agents/' + a['id'], {'metadata': {**metadata, 'jarvis': {**meta, **upgrade}}})
    path = ROOT / 'deploy/.env'
    lines = [line for line in path.read_text().splitlines() if not line.startswith(('JARVIS_RUNTIME_MODEL=', 'JARVIS_INFERENCE_CONFIGURATION='))]
    text = '\n'.join(lines + ['JARVIS_RUNTIME_MODEL=' + args.model,
        'JARVIS_INFERENCE_CONFIGURATION=' + json.dumps(record, sort_keys=True, separators=(',', ':'))]) + '\n'
    temporary = path.with_name('.env.inference-' + secrets.token_hex(4))
    staffing.write_private(temporary, text); os.replace(temporary, path)
    view.update(backup=str(backup.relative_to(ROOT)), employees_left_paused=True,
        next='Refresh owned employee runtimes, recreate CEO/direct-chat env from Compose, pass health/native checks, then resume only these selected employees and restart the operator timer.')
    print(json.dumps(view))


if __name__ == '__main__': main()
