#!/usr/bin/env python3
"""One release lock for both VM administrators; GitLab is the release log."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from uuid import uuid4

ROOT=Path('/home/gaohongyuan1/pudu-materials-operation')
REPO=ROOT/'repo'
WORKSPACES=Path('/srv/pudu-materials-workspaces')
BRANCH='codex/postgres-core'
ADMINS={'gaohongyuan1','weiwei'}
PYTHON=ROOT/'venv/bin/python'
NODE=ROOT/'shared/tools/node-v22.21.0-linux-x64/bin'
UNITS=['pudu-material-'+name for name in ['web','business','effects','card','bridge','assets','english','outbox@ordinary','outbox@cultural','outbox@admin']]

def run(args, *, cwd=REPO, user='gaohongyuan1', env=None):
    command=[str(x) for x in args]
    if user and os.geteuid()==0:command=['runuser','-u',user,'--',*command]
    settings=os.environ.copy();settings.update(env or {})
    return subprocess.check_output(command,cwd=cwd,env=settings,text=True).strip()

def git(*args, cwd=REPO):return run(['git',*args],cwd=cwd)

@contextmanager
def release_lock(path=Path('/run/lock/pudu-material-release.lock')):
    with path.open('a') as lock:
        os.chmod(path,0o600)
        fcntl.flock(lock,fcntl.LOCK_EX)
        yield

def latest(cwd=REPO):
    lines=git('ls-remote','origin','refs/heads/'+BRANCH,cwd=cwd).split()
    if not lines:raise RuntimeError('GitLab release branch is unavailable.')
    return lines[0]

def require_latest(revision, remote):
    if revision != remote:raise RuntimeError('GitLab has a newer submission; this older release will not replace it.')

def integrate(stage, workspace, offered):
    git('fetch',workspace,offered,cwd=stage)
    git('merge','--no-edit','-Xtheirs','FETCH_HEAD',cwd=stage)

def version(path):
    return re.search(r'^APP_VERSION\s*=\s*"(V\d+\.\d+\.\d+)"', (path/'app.py').read_text(),re.M).group(1)

def archive(revision):
    destination=ROOT/'releases'/revision[:12]
    if destination.exists():
        if (destination/'.release_revision').read_text().strip()!=revision:raise RuntimeError('Release directory identity differs.')
        return destination
    with tempfile.TemporaryFile() as archive_file:
        subprocess.run(['runuser','-u','gaohongyuan1','--','git','archive','--format=tar',revision],cwd=REPO,stdout=archive_file,check=True)
        archive_file.seek(0)
        destination.mkdir(mode=0o700)
        with tarfile.open(fileobj=archive_file) as bundle:bundle.extractall(destination,filter='data')
    (destination/'.release_revision').write_text(revision+'\n')
    owner=pwd.getpwnam('gaohongyuan1')
    for path in [destination,*destination.rglob('*')]:
        if not path.is_symlink():os.chown(path,owner.pw_uid,owner.pw_gid)
    if not (destination/'request_web/frontend/dist/index.html').is_file():raise RuntimeError('Frontend build is missing.')
    return destination

def switch(destination):
    temporary=ROOT/('source.next-'+uuid4().hex)
    temporary.symlink_to(destination)
    os.replace(temporary,ROOT/'source')

def queues_idle():
    code="import psycopg; c=psycopg.connect('dbname=pudu_materials'); print(sum(c.execute(\"SELECT count(*) FROM material_ops.\"+t+\" WHERE state='processing'\").fetchone()[0] for t in ('outbox','jobs','effects')))"
    if run([PYTHON,'-c',code])!='0':raise RuntimeError('A worker is processing a write; retry after it finishes.')

def health(expected):
    for _ in range(50):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8501/api/health',timeout=2) as response:local=json.load(response)
            assert local['version']==expected and local['mode']=='postgresql' and local['workflow_write_enabled']
            break
        except (OSError,AssertionError):time.sleep(.5)
    else:raise RuntimeError('Local release health did not become ready.')
    with urllib.request.urlopen('https://materials.pudu.work/api/health',timeout=20) as response:public=json.load(response)
    if local!=public:raise RuntimeError('Public health differs from the VM.')
    return public

def deploy(revision, actor):
    require_latest(revision,latest())
    previous=(ROOT/'source').resolve()
    previous_revision=git('rev-parse',previous.name)
    git('merge-base','--is-ancestor',previous_revision,revision)
    destination=archive(revision)
    if destination==previous:return {'unchanged':True,'revision':revision}
    run(['systemctl','start','pudu-material-backup.service'],user=None)
    assert run(['systemctl','show','pudu-material-backup.service','-p','ExecMainStatus','--value'],user=None)=='0'
    queues_idle()
    stopped=False;changed=False
    try:
        stopped=True
        run(['systemctl','stop',*UNITS],user=None)
        queues_idle()
        require_latest(revision,latest())
        switch(destination);changed=True
        run(['systemctl','daemon-reload'],user=None)
        run(['systemctl','start',*UNITS],user=None)
        result=health(version(destination))
        assert all(state=='active' for state in run(['systemctl','is-active',*UNITS],user=None).splitlines())
    except BaseException:
        if changed:
            run(['systemctl','stop',*UNITS],user=None)
            switch(previous)
        if stopped:run(['systemctl','start',*UNITS],user=None)
        raise
    receipt={'actor':actor,'revision':revision,'previous':previous_revision,'version':result['version'],
             'completed_at':datetime.now(timezone.utc).isoformat(),'health':result}
    log=ROOT/'shared/release-audit.jsonl'
    with log.open('a') as output:output.write(json.dumps(receipt,ensure_ascii=False)+'\n')
    os.chmod(log,0o600)
    return receipt

def publish(workspace, actor):
    workspace=workspace.resolve()
    if workspace!=WORKSPACES/actor:raise RuntimeError('Publish from your own /srv/pudu-materials-workspaces/<account> directory.')
    if run(['git','status','--porcelain'],cwd=workspace,user=actor):raise RuntimeError('Commit your changes before publishing.')
    offered=run(['git','rev-parse','HEAD'],cwd=workspace,user=actor)
    if git('status','--porcelain'):raise RuntimeError('The integration repository has uncommitted work; it will not be overwritten.')
    git('fetch','origin',BRANCH)
    base=git('rev-parse','origin/'+BRANCH)
    git('merge','--ff-only','origin/'+BRANCH)
    before=version(REPO)
    # This private build checkout leaves both developers and the live source untouched.
    builds=ROOT/'shared/builds';builds.mkdir(exist_ok=True)
    owner=pwd.getpwnam('gaohongyuan1')
    with tempfile.TemporaryDirectory(prefix='release-',dir=builds) as temporary:
        stage=Path(temporary);os.chown(stage,owner.pw_uid,owner.pw_gid)
        git('clone','--no-hardlinks',REPO,stage,cwd=ROOT)
        git('remote','set-url','origin',git('remote','get-url','origin'),cwd=stage)
        ssh=git('config','--get','core.sshCommand')
        git('config','core.sshCommand',ssh,cwd=stage)
        git('config','user.name','PUDU VM release ('+actor+')',cwd=stage)
        git('config','user.email',actor+'@localhost',cwd=stage)
        git('fetch','origin',BRANCH,cwd=stage)
        git('checkout','-B',BRANCH,'origin/'+BRANCH,cwd=stage)
        # Three-way merge preserves non-overlapping work. The later submitted
        # workspace wins overlapping text hunks. Structural conflicts stop here.
        integrate(stage,workspace,offered)
        merged=version(stage)
        if tuple(map(int,merged[1:].split('.')))<tuple(map(int,before[1:].split('.'))):
            for name in ['app.py','tests/test_admin_access.py']:
                path=stage/name;path.write_text(path.read_text().replace(merged,before))
        run([PYTHON,'scripts/bump_release_version.py','--root',stage],cwd=stage)
        environment={'PUDU_TEST_DATABASE_DSN':'dbname=pudu_materials_test','PATH':str(NODE)+':'+os.environ['PATH']}
        run([PYTHON,'-m','pytest','tests','-q'],cwd=stage,env=environment)
        frontend=stage/'request_web/frontend'
        old_frontend=REPO/'request_web/frontend'
        if (frontend/'package-lock.json').read_bytes()==(old_frontend/'package-lock.json').read_bytes():
            (frontend/'node_modules').symlink_to(old_frontend/'node_modules',target_is_directory=True)
        else:run([NODE/'npm','ci'],cwd=frontend,env=environment)
        testfiles=sorted(str(path) for path in (frontend/'tests').glob('*.test.mjs'))
        run([NODE/'node','--test',*testfiles],cwd=stage,env=environment)
        run([NODE/'npm','run','build'],cwd=frontend,env=environment)
        git('add','app.py','tests/test_admin_access.py','request_web/frontend/dist',cwd=stage)
        git('diff','--cached','--check',cwd=stage)
        git('commit','-m','Release '+version(stage)+' submitted by '+actor,cwd=stage)
        require_latest(base,latest(stage))
        git('push','origin','HEAD:refs/heads/'+BRANCH,cwd=stage)
        revision=git('rev-parse','HEAD',cwd=stage)
        if git('status','--porcelain'):raise RuntimeError('Integration checkout changed during validation; not overwriting it.')
        git('fetch','origin',BRANCH)
        git('merge','--ff-only','origin/'+BRANCH)
    return deploy(revision,actor)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deploy',metavar='GITLAB_REVISION',help='Deploy an already tested and pushed revision')
    parser.add_argument('--check',action='store_true',help='Read-only workspace and GitLab access check')
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run sudo pudu-release from your own workspace.')
    actor=os.environ.get('SUDO_USER') or 'root'
    if actor not in ADMINS|{'root'}:raise SystemExit('This release entry is configured for gaohongyuan1 and weiwei.')
    with release_lock():
        if args.check:
            if actor not in ADMINS:raise SystemExit('Select an administrator account.')
            workspace=WORKSPACES/actor
            receipt={'actor':actor,'workspace':str(workspace),'branch':run(['git','branch','--show-current'],cwd=workspace,user=actor),
                     'workspace_clean':not run(['git','status','--porcelain'],cwd=workspace,user=actor),
                     'gitlab_head':latest(),'deployment_lock':'shared'}
        elif args.deploy:
            revision=git('rev-parse',args.deploy+'^{commit}')
            receipt=deploy(revision,actor)
        else:receipt=publish(Path.cwd(),actor)
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':main()
