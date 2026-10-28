"""Release recency and cross-process exclusion without production actions."""
from importlib.util import module_from_spec,spec_from_file_location
from pathlib import Path
import multiprocessing
import subprocess
import pytest
pytest.importorskip('fcntl')

spec=spec_from_file_location('vm_release',Path(__file__).resolve().parents[1]/'scripts/vm_release.py')
release=module_from_spec(spec);spec.loader.exec_module(release)

def hold(path,entered,exit):
    with release.release_lock(Path(path)):
        entered.set();exit.wait(10)

def test_older_gitlab_revision_is_refused():
    release.require_latest('latest','latest')
    with pytest.raises(RuntimeError,match='newer submission'):release.require_latest('old','latest')

def test_two_administrators_cannot_hold_the_deployment_lock_together(tmp_path):
    context=multiprocessing.get_context('fork')
    a,b,exit_a,exit_b=[context.Event() for _ in range(4)]
    lock=str(tmp_path/'release.lock')
    one=context.Process(target=hold,args=(lock,a,exit_a));two=context.Process(target=hold,args=(lock,b,exit_b))
    try:
        one.start();assert a.wait(5)
        two.start();assert not b.wait(.1)
        exit_a.set();assert b.wait(5)
    finally:
        exit_a.set();exit_b.set()
        for process in [one,two]:
            if process.pid:process.join(5)
    assert one.exitcode==two.exitcode==0

def test_later_submission_wins_only_overlapping_text_and_preserves_other_work(tmp_path):
    first=tmp_path/'first';last=tmp_path/'last'
    def git(path,*args):return subprocess.check_output(['git',*args],cwd=path,text=True).strip()
    first.mkdir();git(first,'init','-b','main');git(first,'config','user.name','Isolated Test');git(first,'config','user.email','test@localhost')
    (first/'shared.txt').write_text('initial\n');git(first,'add','.');git(first,'commit','-m','base')
    git(tmp_path,'clone',str(first),str(last));git(last,'config','user.name','Second');git(last,'config','user.email','second@localhost')
    (first/'shared.txt').write_text('first\n');(first/'independent.txt').write_text('keep first administrator work\n')
    git(first,'add','.');git(first,'commit','-m','first submission')
    (last/'shared.txt').write_text('last\n');git(last,'add','.');git(last,'commit','-m','later submission')
    release.integrate(first,last,git(last,'rev-parse','HEAD'))
    assert (first/'shared.txt').read_text()=='last\n'
    assert (first/'independent.txt').read_text()=='keep first administrator work\n'

def test_failed_health_restores_previous_source_and_restarts_services(tmp_path,monkeypatch):
    previous=tmp_path/'releases'/'previous';current=tmp_path/'releases'/'current'
    previous.mkdir(parents=True);current.mkdir()
    (tmp_path/'source').symlink_to(previous)
    (current/'app.py').write_text('APP_VERSION = "V3.9.0"\n')
    monkeypatch.setattr(release,'ROOT',tmp_path)
    monkeypatch.setattr(release,'latest',lambda:'new')
    monkeypatch.setattr(release,'git',lambda *args,**kwargs:'old' if args[0]=='rev-parse' else '')
    monkeypatch.setattr(release,'archive',lambda revision:current)
    monkeypatch.setattr(release,'queues_idle',lambda:None)
    calls=[]
    def run(args,**kwargs):
        calls.append(list(map(str,args)))
        return '0' if 'show' in args else ''
    monkeypatch.setattr(release,'run',run)
    monkeypatch.setattr(release,'health',lambda expected:(_ for _ in ()).throw(RuntimeError('health failed')))
    with pytest.raises(RuntimeError,match='health failed'):release.deploy('new','weiwei')
    assert (tmp_path/'source').resolve()==previous
    assert calls[-1]==['systemctl','start',*release.UNITS]
