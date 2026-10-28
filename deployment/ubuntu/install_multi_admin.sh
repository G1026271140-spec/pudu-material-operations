set -eu
root=/home/gaohongyuan1/pudu-materials-operation
getent group pudu-developers >/dev/null || groupadd pudu-developers
usermod -aG pudu-developers gaohongyuan1
usermod -aG pudu-developers weiwei
install -d -m 2770 -o gaohongyuan1 -g pudu-developers /srv/pudu-materials-workspaces
python3 - <<'PY'
from pathlib import Path
import os,pwd,grp,subprocess
root=Path('/home/gaohongyuan1/pudu-materials-operation')
repo=root/'repo';base=Path('/srv/pudu-materials-workspaces')
group=grp.getgrnam('pudu-developers').gr_gid
def git(*args,cwd=repo):return subprocess.check_output(['runuser','-u','gaohongyuan1','--','git',*map(str,args)],cwd=cwd,text=True).strip()
remote=git('remote','get-url','origin');ssh=git('config','--get','core.sshCommand')
for name in ['gaohongyuan1','weiwei']:
    target=base/name
    known=git('config','--global','--get-all','safe.directory') if subprocess.run(['runuser','-u','gaohongyuan1','--','git','config','--global','--get-all','safe.directory'],stdout=subprocess.DEVNULL).returncode==0 else ''
    if str(target) not in known.splitlines():git('config','--global','--add','safe.directory',target)
    if target.exists():
        print('Existing workspace retained: '+str(target));continue
    subprocess.run(['git','-c','safe.directory='+str(repo),'clone','--no-hardlinks',str(repo),str(target)],check=True)
    def localgit(*args):subprocess.run(['git','-c','safe.directory='+str(target),'-C',str(target),*args],check=True)
    localgit('checkout','-b','codex/'+name)
    localgit('remote','set-url','origin',remote)
    localgit('config','core.sshCommand',('sudo -u gaohongyuan1 -- ' if name=='weiwei' else '')+ssh)
    localgit('config','user.name',name)
    localgit('config','user.email',name+'@localhost')
    localgit('config','pull.rebase','false')
    localgit('config','push.default','current')
    owner=pwd.getpwnam(name)
    for path in [target,*target.rglob('*')]:
        if path.is_symlink():continue
        os.chown(path,owner.pw_uid,group)
        os.chmod(path,(path.stat().st_mode & 0o777) | (0o2050 if path.is_dir() else 0o040))
    os.chmod(target,0o2770)
    print('Prepared independent workspace: '+str(target))
wrapper=Path('/usr/local/sbin/pudu-release')
wrapper.write_text('#!/bin/sh\nexec /home/gaohongyuan1/pudu-materials-operation/venv/bin/python /home/gaohongyuan1/pudu-materials-operation/source/scripts/vm_release.py "$@"\n')
os.chmod(wrapper,0o755)
for unit in ['web','business','effects','card','bridge','assets','english','outbox@','reconcile','contacts']:
    suffix='@.service' if unit.endswith('@') else '.service'
    name='pudu-material-'+unit.rstrip('@')+suffix
    folder=Path('/etc/systemd/system')/(name+'.d');folder.mkdir(exist_ok=True)
    (folder/'60-concurrent-edits.conf').write_text('[Service]\nEnvironment=PUDU_CONCURRENT_EDIT_POLICY=last_commit_wins\n')
print('Both administrators use sudo pudu-release; concurrent browser edits use database commit order.')
PY
systemctl daemon-reload
