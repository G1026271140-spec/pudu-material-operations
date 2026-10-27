"""Private, atomic VM backups of PostgreSQL, media and external configuration."""
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tarfile


def main():
    os.umask(0o077)
    root=Path(os.environ['PUDU_DEPLOY_ROOT']).resolve()
    directory=root/'shared/backups'
    directory.mkdir(exist_ok=True,mode=0o700)
    label='pudu-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    dump=directory/(label+'.dump')
    archive=directory/(label+'-files.tar.gz')
    temporary=dump.with_suffix('.dump.partial')
    subprocess.run(['pg_dump','--format=custom','--file='+str(temporary),os.environ['PUDU_DATABASE_DSN']],check=True,capture_output=True)
    subprocess.run(['pg_restore','--list',str(temporary)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    temporary.replace(dump)
    with tarfile.open(str(archive)+'.partial','w:gz') as bundle:
        for name in ('media','config'):
            source=root/'shared'/name
            if source.exists():bundle.add(source,arcname=name)
    Path(str(archive)+'.partial').replace(archive)
    manifest={'created_at':datetime.now().isoformat(timespec='seconds'),
              'revision':(root/'source').resolve().name,
              'files':{p.name:{'bytes':p.stat().st_size,'sha256':sha256(p.read_bytes()).hexdigest()} for p in (dump,archive)}}
    destination=directory/(label+'.json')
    destination.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    for path in (dump,archive,destination):path.chmod(0o600)
    print(json.dumps({'backup_created':True,'manifest':destination.name,'revision':manifest['revision']}))


if __name__=='__main__':main()
