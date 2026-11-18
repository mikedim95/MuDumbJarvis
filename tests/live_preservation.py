#!/usr/bin/env python3
"""Opt-in read-only audit of protected containers, model manifests and inference limits."""
import argparse
import datetime
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def configuration_matches(current, expected):
    parts = {key: current[key] for key in ('Config', 'HostConfig', 'Mounts')}
    if hashlib.sha256(encoded(parts)).hexdigest() == expected:
        return 'exact'
    # Docker builds Mounts from a Go map; its array order can vary on reads.
    # Match the ORIGINAL checksum allowing only this semantically unordered list
    # to permute. Configuration values, environment, bind paths and flags must
    # remain byte-identical. Never print their contents.
    if len(parts['Mounts']) > 8:
        raise ValueError('Protected mount list exceeds the bounded audit; inspect without modifying it')
    prefix = b'{"Config":' + encoded(parts['Config']) + b',"HostConfig":' + encoded(parts['HostConfig']) + b',"Mounts":['
    for mounts in itertools.permutations(encoded(mount) for mount in parts['Mounts']):
        if hashlib.sha256(prefix + b','.join(mounts) + b']}').hexdigest() == expected:
            return 'same values; Docker mount-array order differs'
    raise ValueError('Protected configuration changed; do not restore or modify it automatically')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--phase', choices=('12', '13', '14'), default='12')
    parser.add_argument('--allow-added-model', action='append', default=[], help='Explicit JARVIS-only added alias; original manifests must still match exactly')
    args = parser.parse_args()
    if not args.run:
        print(json.dumps({'status': 'not_executed'}))
        return
    baseline = json.loads((ROOT / '.runtime/phases11-14-baseline.json').read_text())
    receipts = []
    for name, expected in baseline['phase11_exit_configurations'].items():
        current = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
        old = baseline['containers'][name]
        assert current['Id'] == old['id'] and current['State']['StartedAt'] == old['started_at'], name
        assert current['State']['Running'] and not current['State']['Paused'], name
        comparison = configuration_matches(current, expected)
        receipts.append({'name': name, 'id_unchanged': True, 'started_at_unchanged': True,
            'configuration_unchanged': True, 'comparison': comparison, 'running': True, 'paused': False})
    with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=10) as response:
        models = [{key: model[key] for key in ('name', 'size', 'digest')} for model in json.load(response)['models']]
    expected = {m['name']: m for m in baseline['models']}
    observed = {m['name']: m for m in models}
    assert all(observed.get(name) == manifest for name, manifest in expected.items())
    added = set(observed) - set(expected)
    assert added == set(args.allow_added_model), 'Unexpected additions to model inventory'
    assert all(name.startswith('jarvis-') for name in added), 'Only explicitly named JARVIS additions are allowed'
    evidence = {'status': 'passed', 'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'baseline': 'Original container identities/start times and Phase 11 configuration checksums',
        'protected_containers': receipts, 'original_model_manifests_unchanged': True,
        'explicitly_added_model_manifests': [observed[name] for name in sorted(added)], 'models': models,
        'inference_requested': False, 'protected_service_mutations': 0}
    (ROOT / 'docs/evidence' / ('phase' + args.phase + '-preservation.json')).write_text(json.dumps(evidence, indent=2))
    print(json.dumps({'status': 'passed', 'protected_containers': len(receipts), 'original_models_unchanged': len(expected),
        'explicitly_added_models': len(added),
        'inference_requested': False, 'protected_service_mutations': 0}))


if __name__ == '__main__':
    main()
