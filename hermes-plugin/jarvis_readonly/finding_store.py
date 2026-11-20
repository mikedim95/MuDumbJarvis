"""Project-reported references in the General app's existing conversation index."""
from contextlib import closing
import re
import sqlite3


def record(path, fields):
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS project_findings (
            company TEXT NOT NULL, mission TEXT NOT NULL, source TEXT NOT NULL, issue TEXT NOT NULL,
            agent TEXT NOT NULL, run TEXT NOT NULL, artifact TEXT PRIMARY KEY, sha256 TEXT NOT NULL, body TEXT NOT NULL)''')
        db.execute('INSERT OR IGNORE INTO project_findings VALUES (?,?,?,?,?,?,?,?,?)', fields)
        if db.execute('SELECT * FROM project_findings WHERE artifact=?', (fields[6],)).fetchone() != tuple(fields):
            raise ValueError('The General index contains a conflicting artifact receipt.')


def search(path, company, query, mission=None, limit=4):
    if not path.is_file():
        return []
    ignored = {'and','the','for','from','that','this','project','projects','findings','team','what','with','have'}
    terms = list(dict.fromkeys(t for t in re.findall(r'[\w-]{3,}', query.casefold()) if t not in ignored))[:12]
    matches = ['(instr(lower(source || char(10) || body), ?) > 0)' for _ in terms]
    score = ' + '.join(matches) or '0'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_findings'").fetchone():
            return []
        rows = db.execute('SELECT source, mission, issue, artifact, sha256, body, (' + score + ') AS score '
            'FROM project_findings WHERE company=? AND (? IS NULL OR mission=?) '
            + ('AND (' + ' OR '.join(matches) + ') ' if matches else '') +
            'ORDER BY score DESC, rowid DESC LIMIT ?', [*terms, company, mission, mission, *terms, limit]).fetchall()
    return [{'source':r[0], 'mission_id':r[1], 'issue_id':r[2], 'artifact_id':r[3], 'sha256':r[4],
             'text':r[5][:1100], 'kind':'agent-reported project finding'} for r in rows]
