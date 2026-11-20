"""Apply a verified project OS image and retain the previous lab for rollback."""
import argparse
import json
from uuid import UUID

from . import project_containers as labs


def require_idle(board, mission):
    issue = board.api('GET', '/issues/' + mission)
    if not labs.eligible(issue, board.env, keep_completed=True):
        raise ValueError('This project is archived, inactive or outside this deployment.')
    holds = board.api('GET', '/issues/' + mission + '/tree-holds?status=active')
    if (holds.get('holds') if isinstance(holds, dict) else holds):
        raise ValueError('The project has an active stop hold.')
    runs = board.api('GET', '/issues/' + mission + '/runs')
    if issue.get('executionRunId') or any(r.get('status') in ('queued','running','scheduled_retry') for r in runs):
        raise ValueError('Wait for the project’s active work to finish before switching labs.')


def verify_release(ident):
    # Fixed diagnostics run as the employee UID, outside employee-controlled startup files.
    return labs.packages.docker('exec', '--user', '1000:1000', '--workdir', '/project', ident,
        '/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', 'LC_ALL=C', '/bin/sh', '-ec', '''
test "$(id -u)" = 1000
test -w /project && test "$(readlink -f /opt/lab)" = /project
file=$(mktemp /var/tmp/jarvis-lab.XXXXXXXX); trap 'rm -f "$file"' EXIT
printf writable > "$file"; test "$(cat "$file")" = writable
report=/usr/local/share/jarvis/os-maintenance
dpkg-query -W -f='${binary:Package}\\t${Version}\\n' > "$file"
cmp "$file" "$report/after.tsv"
dpkg --audit > "$file"; test ! -s "$file"
test -s "$report/update.log" && test -s "$report/check.log"
cat "$report/verified-at"
tail -1 "$report/remaining.log"
''')


def switch(board, mission, expected, rollback=False):
    mission = str(UUID(mission))
    company = board.env['PAPERCLIP_COMPANY_ID']
    require_idle(board, mission)
    # Record the exact current generation even when adopting an older running lab.
    if not labs.staffing.inspect('container', labs.active_name(company, mission)):
        raise ValueError('The selected project has no existing container.')
    labs.container(company, mission)
    with labs.lab_lock(company, mission, exclusive=True):
        require_idle(board, mission)
        record = labs.selection(company, mission)
        current = record['current']
        old_id = labs.provision(company, mission, current)
        if old_id != expected:
            raise ValueError('The project container changed. Inspect its current ID before switching.')
        if rollback:
            target = record.get('previous')
            if not target or not labs.staffing.inspect('container', target['name']):
                raise ValueError('There is no retained previous lab for this project.')
        else:
            target = labs.writable_release(mission)
            if current['image'] == target['image'] and not current['readonly']:
                return {'container':old_id, 'verification':verify_release(old_id), 'changed':False}
        new_id = labs.provision(company, mission, target)
        try:
            verification = 'Restored verified legacy configuration' if target['readonly'] else verify_release(new_id)
            require_idle(board, mission)
            labs.save_selection(company, mission, target, current)
        except BaseException:
            labs.packages.docker('stop', '--time', '2', new_id)
            raise
        labs.packages.docker('stop', '--time', '2', old_id)
        return {'container':new_id, 'previous_container':old_id, 'image':target['image'],
                'volume':labs.names(mission)[2], 'verification':verification, 'changed':True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mission', type=UUID)
    parser.add_argument('--expected-container', required=True, help='Full ID of the existing project container')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    board = labs.staffing.Board(labs.staffing.settings())
    print(json.dumps(switch(board, str(args.mission), args.expected_container, args.rollback), indent=2))
