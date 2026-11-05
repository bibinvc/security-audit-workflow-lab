import csv
import io
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from app import Store, score, handler_for

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'test.sqlite3'
        self.store = Store(self.path)

    def tearDown(self): self.tmp.cleanup()

    def risk(self, title='Risk', likelihood=3, impact=4):
        return self.store.add_risk(dict(title=title,owner='Process A',likelihood=likelihood,impact=impact,standard='ISO 27001'))

    def audit(self, risk=None):
        return self.store.plan_audit(dict(risk_id=risk or self.risk(),auditor='Auditor X',due='2026-12-01'))

    def finding(self, audit=None):
        return self.store.add_finding(dict(audit_id=audit or self.audit(),title='Observation',evidence='SAMPLE-001'))

    def action(self, due='2026-11-05',title='Improve procedure'):
        return self.store.add_action(dict(finding_id=self.finding(),title=title,owner='Owner X',due=due))

    def ready(self, action):
        self.store.update_action(action,dict(status='In progress'))
        self.store.update_action(action,dict(status='Ready for review'))

    def close(self, action):
        self.ready(action)
        self.store.update_action(action,dict(status='Closed',evidence='SAMPLE-002',reviewer='Reviewer Y'))

    def test_risk_score_bounds(self):
        self.assertEqual(score(5,4),20)
        for args in [(0,2),(2,6),(True,2),(2.5,2)]:
            with self.assertRaises(ValueError): score(*args)

    def test_plan_orders_highest_exposure_first(self):
        self.audit(self.risk('Low',1,2)); self.audit(self.risk('High',5,5))
        self.assertEqual([a['score'] for a in self.store.snapshot()['audits']],[25,2])

    def test_auditor_independence_case_insensitive(self):
        risk=self.risk()
        with self.assertRaises(ValueError): self.store.plan_audit(dict(risk_id=risk,auditor=' process a ',due='2026-12-01'))
        self.assertEqual(self.store.snapshot()['audits'],[])

    def test_id_types_and_missing_records(self):
        for bad in [None,[],{},True,-1,0]:
            with self.assertRaises(ValueError): self.store.plan_audit(dict(risk_id=bad,auditor='X',due='2026-12-01'))
        with self.assertRaises(ValueError): self.store.add_finding(dict(audit_id=999,title='X',evidence='Y'))

    def test_complete_requires_observation_evidence(self):
        audit=self.audit()
        with self.assertRaises(ValueError): self.store.finish_audit(audit)
        self.finding(audit); self.store.finish_audit(audit)
        self.assertEqual(self.store.snapshot()['audits'][0]['status'],'Completed')

    def test_finding_evidence_required(self):
        audit=self.audit()
        with self.assertRaises(ValueError): self.store.add_finding(dict(audit_id=audit,title='X',evidence=' '))
        self.assertFalse(self.store.snapshot()['findings'])

    def test_reject_shortcut_and_keep_history_atomic(self):
        action=self.action(); before=self.store.snapshot()
        with self.assertRaises(ValueError): self.store.update_action(action,dict(status='Closed',evidence='X',reviewer='Y'))
        after=self.store.snapshot()
        self.assertEqual(before['history'],after['history']); self.assertEqual(after['actions'][0]['status'],'Open')

    def test_closure_needs_evidence_and_independent_reviewer(self):
        action=self.action(); self.ready(action)
        for data in [dict(status='Closed'),dict(status='Closed',evidence='X'),dict(status='Closed',evidence='X',reviewer='owner x')]:
            with self.assertRaises(ValueError): self.store.update_action(action,data)
        self.store.update_action(action,dict(status='Closed',evidence='Sample evidence',reviewer='Reviewer'))
        self.assertEqual(self.store.snapshot()['kpis']['evidence_complete_closed'],1)

    def test_reopen_clears_closure_but_keeps_history(self):
        action=self.action(); self.close(action)
        self.store.update_action(action,dict(status='In progress'))
        data=self.store.snapshot()
        self.assertEqual(data['actions'][0]['evidence'],''); self.assertEqual(data['actions'][0]['reviewer'],'')
        self.assertTrue(any('SAMPLE-002' in h['detail'] for h in data['history']))

    def test_overdue_excludes_today_future_and_closed(self):
        self.action('2026-11-04'); self.action('2026-11-05'); self.action('2026-11-06')
        closed=self.action('2026-11-01'); self.close(closed)
        k=self.store.snapshot('2026-11-05')['kpis']
        self.assertEqual(k['actions_overdue'],1); self.assertEqual(k['actions_open'],3)

    def test_empty_denominators_are_null(self):
        k=self.store.snapshot()['kpis']
        self.assertIsNone(k['closure_percent']); self.assertIsNone(k['risk_coverage_percent'])

    def test_coverage_uses_distinct_completed_risks(self):
        risk=self.risk(); self.risk('Not audited')
        for _ in range(2):
            audit=self.audit(risk); self.finding(audit); self.store.finish_audit(audit)
        k=self.store.snapshot()['kpis']
        self.assertEqual(k['risks_audited'],1); self.assertEqual(k['risk_coverage_percent'],50)

    def test_persistence(self):
        self.action(); self.assertEqual(len(Store(self.path).snapshot()['actions']),1)

    def test_export_and_formula_escaping(self):
        self.action(title='=HYPERLINK("x")')
        rows=list(csv.reader(io.StringIO(self.store.jira_csv())))
        self.assertEqual(rows[1][1],'\'=HYPERLINK("x")')
        report=self.store.report('2026-11-05')
        self.assertIn('Synthetic educational data',report); self.assertIn('no live Confluence integration',report)

    def test_bad_date_and_unknown_standard(self):
        with self.assertRaises(ValueError): self.store.plan_audit(dict(risk_id=self.risk(),auditor='Y',due='2026-02-31'))
        with self.assertRaises(ValueError): self.store.add_risk(dict(title='X',owner='Y',likelihood=1,impact=1,standard='Invented'))

    def test_seed_is_idempotent_and_synthetic(self):
        self.assertTrue(self.store.seed()); self.assertFalse(self.store.seed())
        data=self.store.snapshot('2026-11-05')
        self.assertTrue(data['synthetic']); self.assertEqual(data['kpis']['actions_total'],2)
        self.assertEqual(data['kpis']['closure_percent'],50)

    def test_http_local_boundaries_and_json_write(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.store))
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            conn=HTTPConnection('127.0.0.1',server.server_port)
            conn.request('GET','/api/state'); response=conn.getresponse(); self.assertEqual(response.status,200); response.read()
            conn.request('GET','/api/state',headers={'Host':'evil.example'}); response=conn.getresponse(); self.assertEqual(response.status,403); response.read()
            conn.request('POST','/api/risks',body='{}',headers={'Content-Type':'application/json','X-Local-Client':'1','Origin':'https://evil.example'}); response=conn.getresponse(); self.assertEqual(response.status,403); response.read()
            payload=json.dumps(dict(title='HTTP risk',owner='HTTP owner',likelihood=2,impact=3,standard='ISO 27001'))
            conn.request('POST','/api/risks',body=payload,headers={'Content-Type':'application/json','X-Local-Client':'1'}); response=conn.getresponse(); self.assertEqual(response.status,200); response.read()
            conn.request('POST','/api/audits',body=json.dumps(dict(risk_id=[],auditor='X',due='2026-12-01')),headers={'Content-Type':'application/json','X-Local-Client':'1'}); response=conn.getresponse(); self.assertEqual(response.status,400); response.read()
            conn.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()

if __name__ == '__main__': unittest.main(verbosity=2)
