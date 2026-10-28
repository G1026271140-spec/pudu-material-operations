#!/usr/bin/env python3
"""Read-only live VM evidence without credentials or business payloads.

Run as gaohongyuan1 using the VM venv from its source/workspace directory.
Does not write a database, start/restart services or trigger Feishu notifications.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path('/home/gaohongyuan1/pudu-materials-operation')
UNITS = ['pudu-material-'+s+'.service' for s in
         ('web','business','effects','card','bridge','assets','english','outbox@ordinary','outbox@cultural','outbox@admin')]


def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=20).strip()


def collect():
    report = {'checked_at': datetime.now(timezone(timedelta(hours=8))).isoformat(), 'read_only': True, 'errors': []}
    for label, url in (('local_health','http://127.0.0.1:8501/api/health'),
                       ('public_health','https://materials.pudu.work/api/health')):
        try:
            with urllib.request.urlopen(url, timeout=20) as response: report[label] = json.load(response)
        except Exception as exc: report['errors'].append({'check': label, 'type': type(exc).__name__})
    try:
        report['live_release'] = (ROOT/'source').resolve().name
        report['integration_head'] = command('git','-C',str(ROOT/'repo'),'rev-parse','HEAD')
        report['integration_clean'] = not command('git','-C',str(ROOT/'repo'),'status','--porcelain')
        report['gitlab_head'] = command('git','-C',str(ROOT/'repo'),'ls-remote','origin','refs/heads/codex/postgres-core').split()[0]
        report['services'] = {}
        for unit in UNITS:
            raw = command('systemctl','show',unit,'-p','ActiveState','-p','SubState','-p','MainPID')
            report['services'][unit] = dict(line.split('=',1) for line in raw.splitlines())
            pid = report['services'][unit].get('MainPID', '0')
            if pid != '0':
                try: report['services'][unit]['runtime_cwd'] = str((Path('/proc')/pid/'cwd').resolve(strict=True))
                except OSError: report['services'][unit]['runtime_cwd'] = 'unavailable'
        report['timers'] = {}
        for name in ('backup','reconcile','contacts'):
            raw = command('systemctl','show',f'pudu-material-{name}.timer','-p','ActiveState','-p','NextElapseUSecRealtime')
            report['timers'][name] = dict(line.split('=',1) for line in raw.splitlines())
        # Explicit read-only SQL protects this inspection even if code is modified.
        import psycopg
        with psycopg.connect('dbname=pudu_materials',autocommit=True) as conn, conn.transaction():
            conn.execute('SET TRANSACTION READ ONLY'); conn.execute("SET LOCAL TIME ZONE 'Asia/Shanghai'")
            report['mapping'] = {k: conn.execute('SELECT count(*) FROM material_meta.'+k).fetchone()[0] for k in ('tables','fields')}
            report['queues'] = {}
            for name in ('outbox','jobs','effects'):
                report['queues'][name] = {s: c for s,c in conn.execute('SELECT state,count(*) FROM material_ops.'+name+' GROUP BY state ORDER BY state')}
            report['outbox_lanes'] = [{'lane': l, 'state': s, 'count': c} for l,s,c in conn.execute('SELECT lane,state,count(*) FROM material_ops.outbox GROUP BY lane,state ORDER BY lane,state')]
            row = conn.execute('SELECT started_at,completed_at,state,summary FROM material_ops.reconcile_runs ORDER BY started_at DESC LIMIT 1').fetchone()
            if row:
                summary = row[3] or {}
                # Source names, exception strings and record data are deliberately omitted.
                report['latest_reconcile'] = {'started_at': row[0].isoformat(), 'completed_at': row[1].isoformat() if row[1] else None,
                                              'state': row[2], 'summary_keys': sorted(summary)}
        latest = sorted((ROOT/'shared/backups').glob('pudu-*.json'))
        if latest:
            manifest = json.loads(latest[-1].read_text())
            report['latest_backup'] = {'manifest': latest[-1].name, 'created_at': manifest.get('created_at'),
                                       'revision': manifest.get('revision'), 'artifact_names': list(manifest.get('files',{}))}
    except Exception as exc:
        report['errors'].append({'check': 'vm_inspection', 'type': type(exc).__name__})
    report['local_public_equal'] = report.get('local_health') == report.get('public_health') if 'local_health' in report and 'public_health' in report else False
    return report


if __name__ == '__main__':
    data = collect()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    # Queue counts are evidence, not a reason to replay historical failed jobs.
    raise SystemExit(1 if data['errors'] else 0)
