"""Offline, verified database + imaging backups. Restore never overwrites storage."""
from contextlib import closing
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile


def backup(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if not (source / 'kneura.sqlite').is_file():
        raise ValueError('Source database is missing.')
    with tempfile.TemporaryDirectory(prefix='kneura-backup-') as temporary:
        snapshot = Path(temporary) / 'kneura.sqlite'
        with closing(sqlite3.connect(source / 'kneura.sqlite')) as src, closing(sqlite3.connect(snapshot)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Database integrity check failed.')
        members = [('kneura.sqlite', snapshot)]
        studies = source / 'studies'
        if studies.exists():
            for path in sorted(studies.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Backup does not follow imaging symlinks.')
                if path.is_file():
                    members.append((path.relative_to(source).as_posix(), path))
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest = {'schema': 'kneura.backup.v1', 'files': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in members}}
        with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, path in members:
                archive.write(path, name)
            archive.writestr('manifest.json', json.dumps(manifest, sort_keys=True))
    return dict(backup=str(output), files=len(members), verified=True)


def restore(archive_path, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Restore destination must be new. Existing data is never overwritten.')
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) > 100000 or sum(i.file_size for i in archive.infolist()) > 10*1024**3:
            raise ValueError('Invalid or oversized backup.')
        for name in names:
            if '\\' in name or ':' in name or not (destination / name).resolve().is_relative_to(destination):
                raise ValueError('Unsafe archive path.')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('schema') != 'kneura.backup.v1' or set(names) != set(manifest['files']) | {'manifest.json'} or 'kneura.sqlite' not in manifest['files']:
            raise ValueError('Backup manifest mismatch.')
        for name, expected in manifest['files'].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError('Backup content hash failed.')
        destination.mkdir(parents=True)
        for name in manifest['files']:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    with closing(sqlite3.connect(destination / 'kneura.sqlite')) as conn, conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Restored database integrity failed. Do not start the server.')
        conn.execute('DELETE FROM sessions')
        from .audit import verify
        for row in conn.execute('SELECT document FROM cases'):
            case = json.loads(row[0])
            if case.get('auditChain') and not verify(case)['valid']:
                raise ValueError('Restored audit chain failed verification. Do not start the server.')
    return dict(restored=str(destination), verified=True, sessions_revoked=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    save = sub.add_parser('backup')
    save.add_argument('--source', default='.kneura')
    save.add_argument('--output', required=True)
    save.add_argument('--server-stopped', action='store_true', required=True, help='Confirm API/workers are stopped so assets match the database snapshot.')
    load = sub.add_parser('restore')
    load.add_argument('--archive', required=True)
    load.add_argument('--destination', required=True)
    args = parser.parse_args()
    result = backup(args.source, args.output) if args.command == 'backup' else restore(args.archive, args.destination)
    print(json.dumps(result, indent=2))
