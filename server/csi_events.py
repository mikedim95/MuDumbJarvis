"""Deterministic, read-only CSI projections of native Paperclip records.

This is a presentation API, never a task store, scheduler or discovery engine.
An execution receipt establishes where tool output came from; it does not
independently validate every conclusion contained in that output.
"""
import asyncio
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit

MAX_TASKS = 25
MAX_EVENTS = 400
MAX_ITEMS = 80
MAX_GRAPH_NODES = 160
MAX_GRAPH_EDGES = 240
DISCOVERIES = {'identity.partial_match_found', 'network.trace', 'decryption.progress'}
ARTIFACT_KEYS = ('id', 'issueId', 'originalFilename', 'contentType', 'byteSize', 'sha256',
                 'createdByAgentId', 'originatingRunId', 'createdAt')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def compact(value, depth=0):
    """Bound tool payloads without promoting generated strings into events."""
    if depth > 6:
        return '[display depth limit]'
    if isinstance(value, str):
        return value[:2400]
    if isinstance(value, dict):
        return {str(k)[:80]: compact(v, depth + 1) for k, v in list(value.items())[:40]
                if not re.search(r'(?i)(password|secret|token|api.?key|authorization)', str(k))}
    if isinstance(value, list):
        return [compact(v, depth + 1) for v in value[:40]]
    return value if value is None or isinstance(value, (int, float, bool)) else str(value)[:2400]


def public_body(body):
    text = str(body or '')
    # Published updates are available; raw receipt blobs and explicitly marked
    # private reasoning are not a user-facing activity stream.
    text = re.sub(r'<(?:think|analysis)>[\s\S]*?(?:</(?:think|analysis)>|$)', '', text, flags=re.I)
    return '\n'.join(line for line in text.splitlines() if line.strip() != '[JARVIS TOOL EVENT]' and
        not line.lstrip().startswith(('JARVIS_EXECUTION_EVIDENCE=', 'JARVIS_TOOL_EVENT=',
                                      'JARVIS_DISCOVERY_EVENT=')))[:4000].strip()


def source_url(value):
    """A recorded source host is not a packet trace or geolocation result."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            return None
        host = parsed.hostname[:253]
        return {'url': urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))[:1000],
                'host': host, 'observation': 'recorded_source_retrieval',
                'limits': 'Recorded source URL only; no packet route, IP attribution or geolocation was measured.'}
    except ValueError:
        return None


async def build_snapshot(p, task_id, evidence_validator, capability_projection):
    root = await p.issue(task_id)
    all_issues, roster = await asyncio.gather(
        p.request('GET', f'companies/{p.company}/issues?projectId={p.project}'), p.agents())
    scoped = {i['id']: i for i in all_issues if isinstance(i, dict) and i.get('id') and
              i.get('companyId') == p.company and i.get('projectId') == p.project}
    scoped[root['id']] = root
    selected = [root]
    remaining = sorted(scoped.values(), key=lambda i: (i.get('createdAt') or '', i['id']))
    selected_ids = {root['id']}
    while len(selected) < MAX_TASKS:
        batch = [i for i in remaining if i.get('parentId') in selected_ids and i['id'] not in selected_ids]
        if not batch:
            break
        for issue in batch[:MAX_TASKS - len(selected)]:
            selected.append(issue); selected_ids.add(issue['id'])
    truncated = any(i.get('parentId') in selected_ids and i['id'] not in selected_ids for i in remaining)
    semaphore = asyncio.Semaphore(4)

    async def records(issue):
        async with semaphore:
            comments, runs, artifacts = await asyncio.gather(*(
                p.request('GET', f"issues/{issue['id']}/{kind}") for kind in ('comments', 'runs', 'attachments')))
            return issue, comments, runs, artifacts

    histories = await asyncio.gather(*(records(i) for i in selected))
    events, nodes, edges, artifacts = {}, {}, {}, {}
    agents = {a['id']: a for a in roster if isinstance(a, dict) and a.get('id') and
              (not a.get('companyId') or a.get('companyId') == p.company)}
    used_agents = set()

    def add_event(kind, issue, key, title, data, occurred_at=None, provenance='native_record', **refs):
        reference = {'issue_id': issue['id'], **{k: v for k, v in refs.items() if v}}
        row = {'type': kind, 'task_id': issue['id'], 'occurred_at': occurred_at,
               'title': str(title)[:180], 'data': compact(data), 'provenance': provenance, 'source_ref': reference}
        row['id'] = 'csi-' + digest([kind, issue['id'], key])[:24]
        events[row['id']] = row

    def node(kind, native_id, label, issue, status=None, occurred_at=None):
        nonlocal truncated
        nid = kind + ':' + str(native_id)
        if nid not in nodes and len(nodes) >= MAX_GRAPH_NODES:
            truncated = True
            return None
        nodes[nid] = {'id': nid, 'native_id': str(native_id), 'kind': kind, 'label': str(label)[:180], 'status': status}
        add_event('graph.node_discovered', issue, nid, 'Recorded relationship: ' + str(label),
                  {'node': nodes[nid]}, occurred_at)
        return nid

    def edge(source, target, label):
        nonlocal truncated
        if not source or not target:
            return
        eid = 'link-' + digest([source, target, label])[:20]
        if eid not in edges and len(edges) >= MAX_GRAPH_EDGES:
            truncated = True
            return
        edges[eid] = {'id': eid, 'source': source, 'target': target, 'label': label}

    for issue, comments, runs, native_artifacts in histories:
        iid = issue['id']; created = issue.get('createdAt'); updated = issue.get('updatedAt') or created
        task_node = node('task', iid, issue.get('identifier') or issue.get('title') or iid, issue,
                         issue.get('status'), created)
        add_event('task.progress', issue, ['created', created], 'Task recorded in Paperclip',
                  {'identifier': issue.get('identifier'), 'title': issue.get('title')}, created)
        add_event('task.progress', issue, ['state', issue.get('status'), updated],
                  (issue.get('identifier') or iid) + ' · ' + str(issue.get('status')),
                  {'status': issue.get('status'), 'execution_run_id': issue.get('executionRunId')}, updated)
        if issue.get('status') in ('blocked', 'cancelled') or issue.get('executionBlocker'):
            add_event('analysis.warning', issue, ['blocker', issue.get('status'), digest(issue.get('executionBlocker')),
                      digest(issue.get('unblockDescriptor'))], 'Task requires attention',
                      {'status': issue.get('status'), 'blocker': issue.get('executionBlocker'),
                       'next_action': (issue.get('unblockDescriptor') or {}).get('action')}, updated)
        assignee = issue.get('assigneeAgentId')
        if assignee and assignee in agents:
            used_agents.add(assignee); agent = agents[assignee]
            identity = {k: agent.get(k) for k in ('id', 'name', 'role', 'status', 'lifecycleState')}
            capability = capability_projection(agent)
            identity.update(model=capability.get('model'), provider=capability.get('provider'))
            agent_node = node('agent', assignee, agent.get('name') or assignee, issue, agent.get('status'), updated)
            edge(task_node, agent_node, 'assigned to')
            add_event('identity.updated', issue, ['executor', assignee, digest(identity)],
                      'Assigned executor: ' + str(agent.get('name') or assignee),
                      {'identity_kind': 'Paperclip employee', **identity}, updated, agent_id=assignee)
        parent = scoped.get(issue.get('parentId'))
        if parent:
            parent_node = node('task', parent['id'], parent.get('identifier') or parent['id'], issue,
                               parent.get('status'), parent.get('createdAt'))
            edge(parent_node, task_node, 'parent of')
        for dependency in issue.get('blockedBy') or []:
            related = scoped.get(dependency.get('id')) if isinstance(dependency, dict) else None
            if related:
                dep_node = node('task', related['id'], related.get('identifier') or related['id'], issue,
                                related.get('status'), related.get('createdAt'))
                edge(task_node, dep_node, 'depends on')
        for run in sorted(runs, key=lambda r: (r.get('createdAt') or r.get('startedAt') or '', r.get('runId') or ''))[-MAX_ITEMS:]:
            rid = run.get('runId')
            if not rid or (run.get('issueId') and run['issueId'] != iid) or (run.get('companyId') and run['companyId'] != p.company):
                continue
            run_node = node('run', rid, 'Execution ' + rid[:8], issue, run.get('status'), run.get('startedAt'))
            edge(task_node, run_node, 'execution')
            data = {k: run.get(k) for k in ('status', 'startedAt', 'finishedAt', 'error', 'errorCode')}
            occurred = run.get('finishedAt') or run.get('startedAt') or run.get('createdAt')
            failed = run.get('status') in ('failed', 'timed_out', 'interrupted')
            add_event('task.failed' if failed else 'task.progress', issue,
                      ['run', rid, digest(data)], 'Execution ' + str(run.get('status') or 'recorded'),
                      data, occurred, run_id=rid, agent_id=run.get('agentId') or assignee)
            if failed or run.get('error') or run.get('errorCode'):
                add_event('analysis.warning', issue, ['run-error', rid, digest(data)],
                          'Execution error recorded', data, occurred, run_id=rid)
        for artifact in sorted(native_artifacts, key=lambda a: (a.get('createdAt') or '', a.get('id') or ''))[-MAX_ITEMS:]:
            if not artifact.get('id') or (artifact.get('issueId') and artifact['issueId'] != iid):
                continue
            item = {k: artifact.get(k) for k in ARTIFACT_KEYS}
            item['issueId'] = iid
            artifacts[item['id']] = item
            file_node = node('artifact', item['id'], item.get('originalFilename') or item['id'], issue,
                             'recorded', item.get('createdAt'))
            edge(task_node, file_node, 'artifact')
            reference = {'artifact_id': item['id'], 'run_id': item.get('originatingRunId'),
                         'agent_id': item.get('createdByAgentId')}
            add_event('evidence.file_recovered', issue, ['artifact', item['id']],
                      'Artifact recorded: ' + str(item.get('originalFilename') or item['id']),
                      {**item, 'observation': 'Native uploaded artifact; no deleted-file recovery is claimed'},
                      item.get('createdAt'), **reference)
            add_event('evidence.metadata', issue, ['artifact-metadata', item['id'], digest(item)],
                      'Native artifact metadata', item, item.get('createdAt'), **reference)
        for comment in sorted(comments, key=lambda c: (c.get('createdAt') or '', c.get('id') or ''))[-MAX_ITEMS:]:
            if comment.get('issueId') and comment['issueId'] != iid:
                continue
            cid = comment.get('id') or digest(comment)[:24]
            body = public_body(comment.get('body'))
            if body:
                add_event('task.progress', issue, ['comment', cid, digest(body)],
                          'Published agent update' if comment.get('authorAgentId') else 'Recorded operator update',
                          {'text': body, 'update_kind': 'plan' if body.startswith('[JARVIS CEO PLAN') else 'comment'},
                          comment.get('createdAt'), 'agent_summary' if comment.get('authorAgentId') else 'native_record',
                          comment_id=cid, agent_id=comment.get('authorAgentId'))
            for receipt in evidence_validator(comment, issue, runs, p.company):
                if not receipt.get('verified'):
                    continue
                rid = receipt.get('run_id')
                for index, tool in enumerate(receipt.get('tools') or []):
                    if not isinstance(tool, dict):
                        continue
                    tool_id = tool.get('tool_call_id') or digest([tool.get('tool'), tool.get('args'), tool.get('result')])[:24]
                    result = tool.get('result')
                    add_event('task.progress', issue, ['tool', rid, tool_id],
                              'Tool observed: ' + str(tool.get('tool') or 'unknown'),
                              {'tool': tool.get('tool'), 'tool_call_id': tool.get('tool_call_id'),
                               'success': tool.get('success'), 'result': result,
                               'verification': 'Authenticated tool output; conclusions still require review'},
                              comment.get('createdAt'), 'verified_tool_output', run_id=rid,
                              comment_id=cid, agent_id=receipt.get('agent_id'))
                    if tool.get('success') is not True:
                        add_event('analysis.warning', issue, ['tool-failed', rid, tool_id],
                                  'Tool failure recorded', {'tool': tool.get('tool'), 'result': result},
                                  comment.get('createdAt'), 'verified_tool_output', run_id=rid, comment_id=cid)
                    if tool.get('success') is not True or tool.get('tool') in ('publish_artifact', 'request_action_approval') or not isinstance(result, dict):
                        continue
                    discoveries = result.get('discoveries') or result.get('events') or []
                    if not isinstance(discoveries, list):
                        continue
                    for discovery in discoveries[:30]:
                        if not isinstance(discovery, dict) or discovery.get('type') not in DISCOVERIES or not isinstance(discovery.get('data'), dict):
                            continue
                        add_event(discovery['type'], issue, ['discovery', rid, tool_id, digest(discovery)],
                                  discovery.get('title') or discovery['type'], discovery['data'],
                                  comment.get('createdAt'), 'verified_tool_output', run_id=rid, comment_id=cid,
                                  agent_id=receipt.get('agent_id'))
                for source in (receipt.get('source_refs') or [])[:30]:
                    if not isinstance(source, dict):
                        continue
                    recorded = source_url(source.get('url') or source.get('source_url'))
                    if recorded:
                        add_event('network.trace', issue, ['source', rid, recorded['url']],
                                  'Recorded source host: ' + recorded['host'], recorded,
                                  comment.get('createdAt'), 'verified_tool_output', run_id=rid, comment_id=cid)
    agent_views = []
    for aid in sorted(used_agents):
        agent = agents[aid]; info = capability_projection(agent)
        agent_views.append({**{k: agent.get(k) for k in ('id', 'name', 'role', 'status', 'lifecycleState')},
                            'model': info.get('model'), 'provider': info.get('provider')})
    event_list = sorted(events.values(), key=lambda e: (e['occurred_at'] or '', e['id']))
    source_hash = digest(event_list)
    add_event('timeline.updated', root, ['timeline', source_hash], 'Native case timeline updated',
              {'recorded_events': len(event_list), 'scope': 'Paperclip task records and authenticated tool evidence'},
              root.get('updatedAt') or root.get('createdAt'))
    event_list = sorted(events.values(), key=lambda e: (e['occurred_at'] or '', e['id']))
    truncated = truncated or len(event_list) > MAX_EVENTS
    result = {'task_id': root['id'], 'source': 'Paperclip',
              'task': {k: root.get(k) for k in ('id', 'identifier', 'title', 'status', 'assigneeAgentId', 'parentId')},
              'agents': agent_views, 'events': event_list[-MAX_EVENTS:],
              'graph': {'nodes': sorted(nodes.values(), key=lambda n: n['id']),
                        'edges': sorted(edges.values(), key=lambda e: e['id'])},
              'artifacts': sorted(artifacts.values(), key=lambda a: (a.get('createdAt') or '', a['id'])),
              'limits': {'tasks': MAX_TASKS, 'events': MAX_EVENTS, 'truncated': truncated},
              'finding_policy': 'No synthetic progress, identity matches, decryption or network geolocation. Published model summaries are labelled separately from authenticated tool output.'}
    result['snapshot_id'] = digest(result)
    return result
