"""Opt-in live CEO permission verification; never prints credentials.

Run in the JARVIS helper image with the server-side deploy/.env and the private
service network. Optional --objective-id UUID also verifies CEO visibility into
that root and its children/results.

The hire write probe uses incompatible native-runtime inheritance in inspected
Paperclip 2026.1106.0. Approval authority is tested only against an existing
readable neutral approval. Use --verify-approval-guard to create or reuse one
neutral fixture and reject it with board authority afterward; --approval-id
uses an externally supplied fixture whose lifecycle remains with the caller.
A nonexistent approval returns 404 from router.param before the handler's
board-only guard; that 404 does not establish permission denial.
Recheck handler ordering before using another Paperclip version.
This helper creates no task, employee or credential. The opt-in neutral fixture
is the only approval it may create, and that record remains explicitly rejected.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from uuid import UUID, uuid4

import requests


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/ceo-permissions.json'


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise RuntimeError('Missing required environment variable: ' + name)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--objective-id', type=UUID)
    approval_group = parser.add_mutually_exclusive_group()
    approval_group.add_argument('--approval-id', type=UUID,
        help='Existing board-created request_board_approval fixture with no '
             'requesting agent or linked issues; caller manages cleanup')
    approval_group.add_argument('--verify-approval-guard', action='store_true',
        help='Create/reuse and reject one neutral board approval test fixture')
    args = parser.parse_args()
    base = os.environ.get('PAPERCLIP_TEST_URL', os.environ.get(
        'PAPERCLIP_URL', 'http://paperclip:3100')).rstrip('/')
    if not base.endswith('/api'):
        base += '/api'
    company_id = required('PAPERCLIP_COMPANY_ID')
    ceo_id = required('PAPERCLIP_CEO_AGENT_ID')
    worker_id = required('PAPERCLIP_AGENT_ID')
    keys = {
        'board': required('PAPERCLIP_API_KEY'),
        'ceo': required('HERMES_PAPERCLIP_CEO_KEY'),
        'worker': required('HERMES_PAPERCLIP_AGENT_KEY'),
        'anonymous': None,
    }
    check(ceo_id != worker_id, 'CEO and worker must have distinct identities')
    check(keys['ceo'] != keys['worker'], 'CEO and worker keys must differ')
    check(keys['board'] not in (keys['ceo'], keys['worker']),
          'An agent runtime must not use the board key')
    evidence = {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'paperclip_guard_contract': '2026.1106.0 inspected handler ordering',
        'company_id': company_id,
        'passed': False,
        'identities': {},
        'http_checks': [],
    }

    def request(actor, method, path, body=None, expected=200, params=None):
        headers = {'Authorization': 'Bearer ' + keys[actor]} if keys[actor] else {}
        try:
            response = requests.request(method, base + path, headers=headers,
                json=body, params=params, timeout=(5, 30))
        except requests.RequestException as exc:
            raise RuntimeError('Paperclip request failed: ' + type(exc).__name__) from None
        evidence['http_checks'].append({
            'actor': actor, 'method': method, 'path': path,
            'status': response.status_code,
        })
        check(response.status_code == expected,
              actor + ' ' + method + ' ' + path + ' expected HTTP ' +
              str(expected) + ', received ' + str(response.status_code))
        try:
            return response.json()
        except ValueError:
            raise RuntimeError('Paperclip returned invalid JSON for ' + path) from None

    def snapshot():
        agents = request('board', 'GET', '/companies/' + company_id + '/agents')
        approvals = request('board', 'GET', '/companies/' + company_id + '/approvals')
        check(isinstance(agents, list) and isinstance(approvals, list),
              'Expected complete company agent/approval arrays')
        return {
            'employee_count': len(agents),
            'employee_ids': sorted(item['id'] for item in agents),
            'approval_count': len(approvals),
            'approval_ids': sorted(item['id'] for item in approvals),
        }

    before = None
    fixture_id = None
    fixture_created = False
    fixture_title = 'JARVIS CEO permission verification fixture — reject after test'
    fixture_purpose = ('Verify an agent cannot approve a readable neutral approval; '
                       'no operational action authorized')

    def cleanup_fixture():
        if not fixture_id or not args.verify_approval_guard:
            return
        current = request('board', 'GET', '/approvals/' + fixture_id)
        if current.get('status') == 'pending':
            current = request('board', 'POST', '/approvals/' + fixture_id + '/reject',
                {'decisionNote': 'Neutral permission fixture cleanup; no hire or '
                                 'operational action was requested.'})
        check(current.get('status') == 'rejected',
              'Neutral permission fixture did not finish rejected')
        evidence['approval_fixture']['final_status'] = 'rejected'
        evidence['approval_fixture']['cleanup_verified'] = True

    try:
        before = snapshot()
        evidence['before'] = before
        companies = request('board', 'GET', '/companies')
        company = next((item for item in companies if item['id'] == company_id), None)
        check(company is not None, 'Configured company was not visible to the board')
        check(company.get('requireBoardApprovalForNewAgents') is True,
              'Human approval for new hires must be enabled')
        evidence['require_board_approval_for_new_agents'] = True

        for actor, expected_id, can_hire in (
                ('ceo', ceo_id, True), ('worker', worker_id, False)):
            me = request(actor, 'GET', '/agents/me')
            check(me.get('id') == expected_id and me.get('companyId') == company_id,
                  actor + ' credential resolved to the wrong identity/company')
            check(me.get('permissions', {}).get('canCreateAgents') is can_hire,
                  actor + ' canCreateAgents does not match the configured boundary')
            if actor == 'ceo':
                check(me.get('role') == 'ceo', 'CEO identity must have the CEO role')
            else:
                check(me.get('role') != 'ceo', 'Worker must not have legacy CEO authority')
            goals = request(actor, 'GET', '/companies/' + company_id + '/goals')
            tasks = request(actor, 'GET', '/companies/' + company_id + '/issues',
                params={'assigneeAgentId': expected_id,
                        'status': 'todo,in_progress,in_review,blocked'})
            check(isinstance(goals, list) and isinstance(tasks, list),
                  actor + ' context reads did not return arrays')
            check(all(task.get('assigneeAgentId') == expected_id for task in tasks),
                  actor + ' assignment filter returned another assignee')
            evidence['identities'][actor] = {
                'id': me['id'], 'company_id': me['companyId'],
                'name': me.get('name'), 'role': me.get('role'),
                'can_create_agents': can_hire,
                'goals_read': True, 'goal_count': len(goals),
                'assigned_tasks_read': True, 'assigned_task_count': len(tasks),
            }

        request('anonymous', 'GET', '/agents/me', expected=401)

        # The source checks agents:create before this semantic incompatibility.
        # It rejects before svcLifecycle.requestHire or approval insertion.
        probe = {
            'name': 'JARVIS permission probe',
            'role': 'general',
            'adapterType': 'hermes_gateway',
            'inheritRuntimeFrom': 'caller',
        }
        hire_path = '/companies/' + company_id + '/agent-hires'
        rejection = request('ceo', 'POST', hire_path, probe, expected=422)
        message = rejection.get('error', '')
        check('inheritRuntimeFrom=caller requires adapterType=paperclip_runner' in message,
              'CEO hire probe did not reach the known post-authorization guard')
        request('worker', 'POST', hire_path, probe, expected=403)
        request('anonymous', 'POST', hire_path, probe, expected=401)
        evidence['hire_permission_probes'] = {
            'ceo_authorized_before_semantic_guard': True,
            'ceo_status': 422, 'worker_status': 403, 'anonymous_status': 401,
        }

        # router.param('id') checks readability/existence before assertBoard.
        # A nonexistent-ID 404 proves missing-resource behavior, not authority.
        missing_id = str(uuid4())
        request('ceo', 'POST', '/approvals/' + missing_id + '/approve',
                {'decisionNote': 'Missing-resource boundary verification'}, expected=404)
        evidence['missing_approval_probe'] = {
            'status': 404, 'proves_board_only_denial': False,
        }
        evidence['ceo_cannot_approve_hiring'] = False
        if args.verify_approval_guard:
            approvals = request('board', 'GET', '/companies/' + company_id + '/approvals')
            matching = [item for item in approvals
                if item.get('type') == 'request_board_approval'
                and item.get('payload', {}).get('testFixture') is True
                and item.get('payload', {}).get('title') == fixture_title
                and item.get('payload', {}).get('purpose') == fixture_purpose]
            check(len(matching) <= 1, 'Duplicate neutral permission fixtures exist')
            if matching:
                fixture_id = matching[0]['id']
            else:
                fixture = request('board', 'POST',
                    '/companies/' + company_id + '/approvals', {
                        'type': 'request_board_approval',
                        'requestedByAgentId': None,
                        'issueIds': [],
                        'payload': {
                            'title': fixture_title,
                            'purpose': fixture_purpose,
                            'testFixture': True,
                        },
                    }, expected=201)
                fixture_id = fixture['id']
                fixture_created = True
            evidence['approval_fixture'] = {
                'id': fixture_id, 'type': 'request_board_approval',
                'created_by_helper': fixture_created,
                'reused_existing_fixture': not fixture_created,
                'requested_by_agent_id': None, 'linked_issue_ids': [],
            }
        else:
            check(args.approval_id is not None,
                  'A real readable neutral approval fixture is required: use '
                  '--verify-approval-guard or --approval-id. Missing-ID 404 '
                  'is not approval-denial proof.')
            fixture_id = str(args.approval_id)
            evidence['approval_fixture'] = {
                'id': fixture_id, 'created_by_helper': False,
                'cleanup_managed_by_caller': True,
            }
        fixture = request('ceo', 'GET', '/approvals/' + fixture_id)
        check(fixture.get('companyId') == company_id and
              fixture.get('type') == 'request_board_approval' and
              fixture.get('status') in ('pending', 'rejected') and
              fixture.get('requestedByAgentId') is None,
              'Approval fixture must be a pending/rejected board-created '
              'neutral request with no requesting agent')
        initial_status = fixture['status']
        evidence['approval_fixture']['initial_status'] = initial_status
        linked = request('board', 'GET', '/approvals/' + fixture_id + '/issues')
        check(linked == [], 'Permission fixture must not be linked to a task')
        request('ceo', 'POST', '/approvals/' + fixture_id + '/approve',
                {'decisionNote': 'Permission boundary verification'}, expected=403)
        unchanged = request('board', 'GET', '/approvals/' + fixture_id)
        check(unchanged.get('status') == initial_status,
              'Agent approval probe unexpectedly changed the neutral fixture')
        evidence['board_only_approval_probe'] = {
            'id': fixture_id, 'type': 'request_board_approval',
            'ceo_read_status': 200, 'ceo_approve_status': 403,
            'status_after_agent_attempt': initial_status,
        }
        evidence['ceo_cannot_approve_hiring'] = True

        if args.objective_id:
            objective_id = str(args.objective_id)
            root = request('ceo', 'GET', '/issues/' + objective_id)
            check(root.get('companyId') == company_id and
                  root.get('assigneeAgentId') == ceo_id,
                  'Optional root is not assigned to this CEO in this company')
            root_comments = request('ceo', 'GET', '/issues/' + objective_id + '/comments')
            root_runs = request('ceo', 'GET', '/issues/' + objective_id + '/runs')
            company_issues = request('ceo', 'GET', '/companies/' + company_id + '/issues',
                                    params={'projectId': root['projectId']})
            children = [item for item in company_issues
                        if item.get('parentId') == objective_id]
            child_proofs = []
            for item in children:
                child = request('ceo', 'GET', '/issues/' + item['id'])
                check(child.get('companyId') == company_id and
                      child.get('parentId') == objective_id,
                      'Unexpected child company/parent scope')
                comments = request('ceo', 'GET', '/issues/' + item['id'] + '/comments')
                runs = request('ceo', 'GET', '/issues/' + item['id'] + '/runs')
                child_proofs.append({
                    'id': child['id'], 'identifier': child.get('identifier'),
                    'parent_id': objective_id,
                    'assignee_agent_id': child.get('assigneeAgentId'),
                    'status': child.get('status'), 'comment_count': len(comments),
                    'run_statuses': [run.get('status') for run in runs],
                    'ceo_can_read_result': True,
                })
            evidence['objective_read_proof'] = {
                'id': objective_id, 'identifier': root.get('identifier'),
                'assignee_agent_id': root['assigneeAgentId'],
                'status': root.get('status'),
                'comment_count': len(root_comments),
                'run_statuses': [run.get('status') for run in root_runs],
                'children': child_proofs,
            }

        cleanup_fixture()
        after = snapshot()
        evidence['after'] = after
        check(after['employee_ids'] == before['employee_ids'],
              'Permission verification changed company employees')
        expected_approval_ids = set(before['approval_ids'])
        if fixture_created:
            expected_approval_ids.add(fixture_id)
        check(set(after['approval_ids']) == expected_approval_ids,
              'Approval records changed beyond the explicit neutral fixture')
        evidence['no_employee_created'] = True
        evidence['approval_records_created'] = [fixture_id] if fixture_created else []
        evidence['only_explicit_neutral_fixture_added'] = True
        evidence['passed'] = True
    except Exception as exc:
        # All errors raised above contain fixed labels/statuses, not response
        # bodies, authorization headers, adapter configuration or credentials.
        evidence['failure'] = type(exc).__name__ + ': ' + str(exc)
        try:
            cleanup_fixture()
        except Exception as cleanup_error:
            evidence['approval_fixture_cleanup_failure'] = (
                type(cleanup_error).__name__ + ': ' + str(cleanup_error))
        if before is not None and 'after' not in evidence:
            try:
                evidence['after'] = snapshot()
                evidence['no_employee_created'] = (
                    evidence['after']['employee_ids'] == before['employee_ids'])
            except Exception:
                evidence['after_snapshot_unavailable'] = True
        raise
    finally:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(evidence, indent=2) + '\n')

    print('PASS: separate CEO/worker authentication, context reads, hiring and '
          'board-approval boundaries; no employees created.')
    if args.verify_approval_guard:
        print('Neutral approval fixture:', fixture_id, 'rejected;',
              'created' if fixture_created else 'reused')
    print('Evidence:', OUT)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('FAIL:', type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
