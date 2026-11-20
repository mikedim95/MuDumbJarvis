"""Read the lifecycle service's last verified project-container observations."""
import ipaddress
import json
from pathlib import Path
import time

SNAPSHOT = Path(__file__).parent / 'logs/project-containers.json'
NETWORK = 'jarvis-projects-local'


def containers(company):
    try:
        record = json.loads(SNAPSHOT.read_text())
        if (record['company'] != company or record['network'] != NETWORK
                or not 0 <= time.time() - record['at'] < 60):
            return None
        states = record['projects']
        addresses = record.get('bridge_ipv4', {})
        if not isinstance(states, dict) or not isinstance(addresses, dict):
            return None
        result = {}
        for mission, state in states.items():
            if state not in ('running', 'unavailable'):
                continue
            info = {'status':state, 'observed_at':record['at'], 'source':'Docker project lifecycle service'}
            if state == 'running':
                info['network'] = NETWORK
                address = addresses.get(mission)
                if isinstance(address, str):
                    try:
                        info['ipv4'] = str(ipaddress.IPv4Address(address))
                    except ipaddress.AddressValueError:
                        pass
            result[mission] = info
        return result
    except (OSError, KeyError, TypeError, ValueError):
        return None


def details(snapshot, mission):
    if snapshot is None:
        return {'status':'unconfirmed'}
    return snapshot.get(mission, {'status':'inactive'})
