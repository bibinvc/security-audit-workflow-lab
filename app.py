"""AI-assisted educational audit workflow. Synthetic data; not a compliance product."""
from __future__ import annotations
import argparse
import csv
import io
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STANDARDS = ('ISO 19011', 'ISO 27001', 'NEN 7510', 'ISO 9001', 'ISO 27701', 'ISO 27018')
TRANSITIONS = {'Open': {'In progress'}, 'In progress': {'Ready for review'},
               'Ready for review': {'In progress', 'Closed'}, 'Closed': {'In progress'}}

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def clean(value, label, limit=500, required=True):
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        raise ValueError(f'{label}: enter {1 if required else 0} to {limit} characters.')
    return value.strip()

def day(value):
    if not isinstance(value, str):
        raise ValueError('Date must be YYYY-MM-DD.')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('Date must be YYYY-MM-DD.') from exc
    if parsed.isoformat() != value:
        raise ValueError('Date must be YYYY-MM-DD.')
    return value

def score(likelihood, impact):
    if any(type(x) is not int or not 1 <= x <= 5 for x in (likelihood, impact)):
        raise ValueError('Likelihood and impact must be integers from 1 to 5.')
    return likelihood * impact

def csv_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r')) else value

def identifier(value):
    if type(value) is not int or value < 1:
        raise ValueError('Record identifier must be a positive integer.')
    return value

class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS risks (
              id INTEGER PRIMARY KEY,title TEXT NOT NULL,owner TEXT NOT NULL,
              likelihood INTEGER NOT NULL,impact INTEGER NOT NULL,standard TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audits (
              id INTEGER PRIMARY KEY,risk_id INTEGER NOT NULL REFERENCES risks(id),
              auditor TEXT NOT NULL,due TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'Planned');
            CREATE TABLE IF NOT EXISTS findings (
              id INTEGER PRIMARY KEY,audit_id INTEGER NOT NULL REFERENCES audits(id),
              title TEXT NOT NULL,evidence TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS actions (
              id INTEGER PRIMARY KEY,finding_id INTEGER NOT NULL REFERENCES findings(id),
              title TEXT NOT NULL,owner TEXT NOT NULL,due TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'Open',evidence TEXT NOT NULL DEFAULT '',
              reviewer TEXT NOT NULL DEFAULT '',updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history (
              id INTEGER PRIMARY KEY,entity TEXT NOT NULL,entity_id INTEGER NOT NULL,
              at TEXT NOT NULL,detail TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def log(db, entity, entity_id, detail):
        db.execute('INSERT INTO history(entity,entity_id,at,detail) VALUES(?,?,?,?)',
                   (entity, entity_id, now(), detail))

    def add_risk(self, data):
        title, owner = clean(data.get('title'), 'Risk title'), clean(data.get('owner'), 'Process owner', 100)
        likelihood, impact = data.get('likelihood'), data.get('impact')
        score(likelihood, impact)
        standard = data.get('standard')
        if standard not in STANDARDS:
            raise ValueError('Choose an indicative standard label.')
        with self.connect() as db:
            rid = db.execute('INSERT INTO risks(title,owner,likelihood,impact,standard) VALUES(?,?,?,?,?)',
                             (title, owner, likelihood, impact, standard)).lastrowid
            self.log(db, 'risk', rid, 'Risk registered')
            return rid

    def plan_audit(self, data):
        risk_id = identifier(data.get('risk_id'))
        auditor = clean(data.get('auditor'), 'Auditor', 100)
        due = day(data.get('due'))
        with self.connect() as db:
            risk = db.execute('SELECT * FROM risks WHERE id=?', (risk_id,)).fetchone()
            if not risk:
                raise ValueError('Select an existing risk.')
            if risk['owner'].casefold() == auditor.casefold():
                raise ValueError('Auditor must differ from the process owner.')
            aid = db.execute('INSERT INTO audits(risk_id,auditor,due) VALUES(?,?,?)',
                             (risk['id'], auditor, due)).lastrowid
            self.log(db, 'audit', aid, 'Independent auditor assigned; audit planned')
            return aid

    def finish_audit(self, audit_id):
        audit_id = identifier(audit_id)
        with self.connect() as db:
            audit = db.execute('SELECT * FROM audits WHERE id=?', (audit_id,)).fetchone()
            if not audit:
                raise ValueError('Audit not found.')
            # Completion in this lab means a finding/evidence record has been entered.
            if not db.execute('SELECT 1 FROM findings WHERE audit_id=?', (audit_id,)).fetchone():
                raise ValueError('Record at least one finding with evidence before completion.')
            if audit['status'] == 'Completed':
                raise ValueError('Audit is already completed.')
            db.execute("UPDATE audits SET status='Completed' WHERE id=?", (audit_id,))
            self.log(db, 'audit', audit_id, 'Audit marked completed after finding/evidence entry')

    def add_finding(self, data):
        audit_id = identifier(data.get('audit_id'))
        title = clean(data.get('title'), 'Finding title')
        evidence = clean(data.get('evidence'), 'Finding evidence', 2000)
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM audits WHERE id=?', (audit_id,)).fetchone():
                raise ValueError('Select an existing audit.')
            fid = db.execute('INSERT INTO findings(audit_id,title,evidence) VALUES(?,?,?)',
                             (data['audit_id'], title, evidence)).lastrowid
            self.log(db, 'finding', fid, 'Finding recorded with evidence reference')
            return fid

    def add_action(self, data):
        finding_id = identifier(data.get('finding_id'))
        title = clean(data.get('title'), 'Action title')
        owner = clean(data.get('owner'), 'Action owner', 100)
        due = day(data.get('due'))
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM findings WHERE id=?', (finding_id,)).fetchone():
                raise ValueError('Select an existing finding.')
            aid = db.execute('INSERT INTO actions(finding_id,title,owner,due,updated) VALUES(?,?,?,?,?)',
                             (data['finding_id'], title, owner, due, now())).lastrowid
            self.log(db, 'action', aid, 'Corrective action assigned; status Open')
            return aid

    def update_action(self, action_id, data):
        action_id = identifier(action_id)
        status = data.get('status')
        evidence = clean(data.get('evidence', ''), 'Closure evidence', 2000, False)
        reviewer = clean(data.get('reviewer', ''), 'Reviewer', 100, False)
        with self.connect() as db:
            action = db.execute('SELECT * FROM actions WHERE id=?', (action_id,)).fetchone()
            if not action:
                raise ValueError('Action not found.')
            if status not in TRANSITIONS[action['status']]:
                raise ValueError('Invalid next status. Follow Open > In progress > Ready for review > Closed.')
            if status == 'Closed':
                if not evidence or not reviewer:
                    raise ValueError('Closure requires evidence and a named reviewer.')
                if reviewer.casefold() == action['owner'].casefold():
                    raise ValueError('Reviewer must differ from action owner.')
            # Reopening clears the old closure claim; the timestamped history retains it.
            if action['status'] == 'Closed':
                evidence, reviewer = '', ''
            db.execute('UPDATE actions SET status=?,evidence=?,reviewer=?,updated=? WHERE id=?',
                       (status, evidence, reviewer, now(), action_id))
            self.log(db, 'action', action_id,
                     f"{action['status']} -> {status}; reviewer: {reviewer or '-'}; evidence: {evidence or '-'}")

    def snapshot(self, as_of=None):
        as_of = day(as_of or date.today().isoformat())
        with self.connect() as db:
            risks = [dict(r) for r in db.execute('SELECT *,likelihood*impact AS score FROM risks ORDER BY score DESC,id')]
            audits = [dict(r) for r in db.execute('''SELECT audits.*,risks.title AS risk,risks.owner,
                    risks.standard,risks.likelihood*risks.impact AS score FROM audits
                    JOIN risks ON risks.id=audits.risk_id ORDER BY score DESC,due,id''')]
            findings = [dict(r) for r in db.execute('SELECT * FROM findings ORDER BY id')]
            actions = [dict(r) for r in db.execute('SELECT * FROM actions ORDER BY due,id')]
            history = [dict(r) for r in db.execute('SELECT * FROM history ORDER BY id DESC')]
        total = len(actions)
        closed = sum(a['status'] == 'Closed' for a in actions)
        complete = sum(a['status'] == 'Closed' and bool(a['evidence']) and bool(a['reviewer']) for a in actions)
        covered = len({a['risk_id'] for a in audits if a['status'] == 'Completed'})
        kpis = {'actions_total': total, 'actions_open': total-closed,
                'actions_overdue': sum(a['status'] != 'Closed' and a['due'] < as_of for a in actions),
                'actions_closed': closed, 'evidence_complete_closed': complete,
                'closure_percent': round(100*closed/total, 1) if total else None,
                'risks_total': len(risks), 'risks_audited': covered,
                'risk_coverage_percent': round(100*covered/len(risks), 1) if risks else None}
        return {'synthetic': True, 'as_of': as_of, 'standards': list(STANDARDS), 'risks': risks,
                'audits': audits, 'findings': findings, 'actions': actions, 'history': history, 'kpis': kpis}

    def jira_csv(self):
        # Generic CSV field names. Importer mapping and project-specific fields still need review.
        out = io.StringIO(newline='')
        writer = csv.writer(out)
        writer.writerow(['Issue Type', 'Summary', 'Description', 'Status', 'Due Date', 'Labels'])
        for a in self.snapshot()['actions']:
            desc = f"Finding #{a['finding_id']}; owner label: {a['owner']}; evidence: {a['evidence']}; reviewer: {a['reviewer']}"
            writer.writerow([csv_cell(x) for x in ('Task', a['title'], desc, a['status'], a['due'], 'audit-lab-synthetic')])
        return out.getvalue()

    def report(self, as_of=None):
        data = self.snapshot(as_of)
        k = data['kpis']
        safe = lambda value: str(value).replace('|', '\\|').replace('\n', ' ')
        lines = ['# Internal audit workflow: sample management report', '',
                 '**Synthetic educational data. Not an audit opinion or conformity assessment.**', '',
                 f"As of: {data['as_of']}", '',
                 f"- Actions: {k['actions_total']} total; {k['actions_open']} open; {k['actions_overdue']} overdue.",
                 f"- Closure: {k['actions_closed']}/{k['actions_total']} actions; {k['closure_percent']}% (null when no actions).",
                 f"- Closed actions with evidence/reviewer: {k['evidence_complete_closed']}.",
                 f"- Completed-audit risk coverage: {k['risks_audited']}/{k['risks_total']}; {k['risk_coverage_percent']}%.", '',
                 'Closure is a workflow count, not proof of corrective-action effectiveness.',
                 'Coverage counts distinct registered risks with a completed audit, not standard-clause coverage.', '',
                 '## Risk-prioritised audit plan', '', '| Risk | Score | Standard label | Auditor | Due | Status |',
                 '| --- | --- | --- | --- | --- | --- |']
        for a in data['audits']:
            lines.append('| ' + ' | '.join(safe(a[x]) for x in ('risk','score','standard','auditor','due','status')) + ' |')
        lines += ['', '## Corrective actions', '', '| Action | Owner | Due | Status | Evidence | Reviewer |',
                  '| --- | --- | --- | --- | --- | --- |']
        for a in data['actions']:
            lines.append('| ' + ' | '.join(safe(a[x]) for x in ('title','owner','due','status','evidence','reviewer')) + ' |')
        lines += ['', '## Standards and tooling scope', '',
                  'ISO 19011, ISO 27001, NEN 7510, ISO 9001, ISO 27701 and ISO 27018 are indicative labels only.',
                  'No copyrighted standard clauses, conformity claims, real healthcare records or certifications are supplied.',
                  'This Markdown is a copy/paste starting point for Confluence; no live Confluence integration was tested.', '']
        return '\n'.join(lines)

    def seed(self):
        if self.snapshot()['risks']:
            return False
        r1 = self.add_risk({'title':'Sample: access reviews lack follow-up','owner':'Process A','likelihood':4,'impact':5,'standard':'ISO 27001'})
        r2 = self.add_risk({'title':'Sample: privacy retention instructions unclear','owner':'Process B','likelihood':3,'impact':4,'standard':'NEN 7510'})
        r3 = self.add_risk({'title':'Sample: procedure version not visible','owner':'Process C','likelihood':2,'impact':3,'standard':'ISO 9001'})
        a1 = self.plan_audit({'risk_id':r1,'auditor':'Auditor X','due':'2026-11-20'})
        self.plan_audit({'risk_id':r2,'auditor':'Auditor Y','due':'2026-12-01'})
        self.plan_audit({'risk_id':r3,'auditor':'Auditor X','due':'2026-12-10'})
        f1 = self.add_finding({'audit_id':a1,'title':'Sample: no owner recorded for review actions','evidence':'DEMO-EVIDENCE-001: fictitious review sheet'})
        self.finish_audit(a1)
        self.add_action({'finding_id':f1,'title':'Sample: assign access-review follow-up owner','owner':'Action Owner A','due':'2026-11-03'})
        action = self.add_action({'finding_id':f1,'title':'Sample: document review procedure','owner':'Action Owner B','due':'2026-11-25'})
        self.update_action(action, {'status':'In progress'})
        self.update_action(action, {'status':'Ready for review'})
        self.update_action(action, {'status':'Closed','evidence':'DEMO-EVIDENCE-002: fictitious revised procedure','reviewer':'Reviewer X'})
        return True

def handler_for(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, body, content_type='application/json; charset=utf-8', filename=None):
            body = body.encode('utf-8') if isinstance(body, str) else body
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            if filename:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def allowed(self, write=False):
            origins = {f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'}
            if 'http://' + self.headers.get('Host','') not in origins:
                self.send(403, json.dumps({'error':'Local Host required.'})); return False
            origin = self.headers.get('Origin')
            if origin and origin not in origins:
                self.send(403, json.dumps({'error':'Cross-origin requests rejected.'})); return False
            if write and (self.headers.get('X-Local-Client') != '1' or self.headers.get('Content-Type') != 'application/json'):
                self.send(403, json.dumps({'error':'JSON and local client header required.'})); return False
            return True

        def do_GET(self):
            if not self.allowed(): return
            if self.path == '/api/state':
                self.send(200,json.dumps(store.snapshot())); return
            if self.path == '/exports/jira.csv':
                self.send(200,store.jira_csv(),'text/csv; charset=utf-8','jira-actions.csv'); return
            if self.path == '/exports/confluence.md':
                self.send(200,store.report(),'text/markdown; charset=utf-8','audit-report.md'); return
            static = {'/':('index.html','text/html; charset=utf-8'), '/style.css':('style.css','text/css'), '/app.js':('app.js','text/javascript')}
            if self.path in static:
                file, mime = static[self.path]
                self.send(200,(ROOT/'static'/file).read_bytes(),mime)
            else:
                self.send(404,json.dumps({'error':'Not found.'}))

        def do_POST(self):
            if not self.allowed(True): return
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 65536: raise ValueError('Request body must be 1 to 65536 bytes.')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data,dict): raise ValueError('JSON object required.')
                methods = {'/api/risks':store.add_risk,'/api/audits':store.plan_audit,
                           '/api/findings':store.add_finding,'/api/actions':store.add_action}
                if self.path in methods:
                    result = methods[self.path](data)
                elif self.path == '/api/action-status':
                    result = store.update_action(data.get('id'), data)
                elif self.path == '/api/audit-complete':
                    result = store.finish_audit(data.get('id'))
                else:
                    self.send(404,json.dumps({'error':'Not found.'})); return
                self.send(200,json.dumps({'ok':True,'id':result}))
            except (ValueError, TypeError, sqlite3.IntegrityError, OverflowError) as exc:
                self.send(400,json.dumps({'error':str(exc)}))
    return Handler

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=str(ROOT/'data'/'lab.sqlite3'))
    parser.add_argument('--port', type=int, default=9877)
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args()
    path = Path(args.db)
    path.parent.mkdir(parents=True,exist_ok=True)
    store = Store(path)
    if args.demo: store.seed()
    print(f'Local educational audit lab: http://127.0.0.1:{args.port} (synthetic data only)',flush=True)
    try:
        ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(store)).serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')

if __name__ == '__main__':
    main()
