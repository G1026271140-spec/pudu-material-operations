"""Private, atomic VM backups of PostgreSQL, media and external configuration."""
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tarfile


def fingerprint(conn):
    """Digest every persisted row, including projections, audit and outbox."""
    from psycopg import sql
    result={}
    tables=[('material_data',r[0],'_record_key') for r in conn.execute('SELECT sql_table FROM material_meta.tables ORDER BY table_id')]
    tables += [('material_ops',r[0],None) for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='material_ops' AND table_type='BASE TABLE' ORDER BY table_name")]
    tables += [('material_meta','tables',None),('material_meta','fields',None)]
    for schema,name,key in tables:
        # JSONB textual ordering is deterministic; ordering the serialized rows
        # also covers operation tables that use different primary-key shapes.
        rows=conn.execute(sql.SQL('SELECT to_jsonb(t)::text FROM {}.{} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(schema),sql.Identifier(name)))
        digest=sha256();count=0
        for row in rows:
            digest.update(row[0].encode());digest.update(b'\n');count+=1
        result[schema+'.'+name]={'rows':count,'sha256':digest.hexdigest()}
    return result


def main():
    os.umask(0o077)
    root=Path(os.environ['PUDU_DEPLOY_ROOT']).resolve()
    directory=root/'shared/backups'
    directory.mkdir(exist_ok=True,mode=0o700)
    label='pudu-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    dump=directory/(label+'.dump')
    archive=directory/(label+'-files.tar.gz')
    temporary=dump.with_suffix('.dump.partial')
    import psycopg
    with psycopg.connect(os.environ['PUDU_DATABASE_DSN'],autocommit=True) as conn, conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        snapshot=conn.execute('SELECT pg_export_snapshot()').fetchone()[0]
        subprocess.run(['pg_dump','--format=custom','--snapshot='+snapshot,'--file='+str(temporary),os.environ['PUDU_DATABASE_DSN']],check=True,capture_output=True)
        database_fingerprint=fingerprint(conn)
    subprocess.run(['pg_restore','--list',str(temporary)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    temporary.replace(dump)
    with tarfile.open(str(archive)+'.partial','w:gz') as bundle:
        for name in ('media','config'):
            source=root/'shared'/name
            if source.exists():bundle.add(source,arcname=name)
        extension=root/'shared/extensions/material-automation'
        if extension.exists():
            from io import BytesIO
            files=[extension/'config.toml',*(extension/'state').glob('*.json')]
            for source in files:
                if not source.is_file():continue
                content=source.read_bytes()
                if source.suffix=='.json':json.loads(content)
                member=tarfile.TarInfo('extension-state/material-automation/'+str(source.relative_to(extension)))
                member.mode=0o600;member.size=len(content)
                bundle.addfile(member,BytesIO(content))
    Path(str(archive)+'.partial').replace(archive)
    manifest={'created_at':datetime.now().isoformat(timespec='seconds'),
              'revision':(root/'source').resolve().name,
              'database_fingerprint':database_fingerprint,
              'files':{p.name:{'bytes':p.stat().st_size,'sha256':sha256(p.read_bytes()).hexdigest()} for p in (dump,archive)}}
    destination=directory/(label+'.json')
    destination.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    for path in (dump,archive,destination):path.chmod(0o600)
    print(json.dumps({'backup_created':True,'manifest':destination.name,'revision':manifest['revision']}))


if __name__=='__main__':main()
