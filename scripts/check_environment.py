"""Fast Windows prototype preflight; never imports Torch. Paths are project-relative."""
import argparse
import hashlib
import importlib.util
from importlib.metadata import version, PackageNotFoundError
import os
from pathlib import Path
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hash', action='store_true')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--skip-port', action='store_true')
    args = parser.parse_args()
    failures = []

    def check(ok, label, remedy):
        print(f"{'PASS' if ok else 'FAIL'} {label}" + (f' — {remedy}' if not ok else ''), flush=True)
        if not ok:
            failures.append(label)

    check(sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32, 'Python 3.12 x64', 'Recreate .venv with py -3.12 -m venv .venv (64-bit Python).')
    modules = {'fastapi': 'fastapi', 'uvicorn': 'uvicorn', 'SQLAlchemy': 'sqlalchemy', 'pandas': 'pandas', 'pydicom': 'pydicom', 'Pillow': 'PIL', 'pytest': 'pytest', 'httpx': 'httpx', 'python-multipart': 'python_multipart', 'google-genai': 'google.genai', 'torch': 'torch', 'torchvision': 'torchvision'}
    for line in (ROOT / 'backend 1/requirements.txt').read_text().splitlines():
        if '==' not in line:
            continue
        package, expected = line.split('==')
        package = package.split('[')[0]
        try:
            found = version(package)
            available = importlib.util.find_spec(modules[package]) is not None
        except (PackageNotFoundError, ModuleNotFoundError):
            found, available = 'missing', False
        check(available and found == expected, f'{package} {found}', 'Run .\\run_prototype.ps1 -Install -MockLlm to install canonical requirements.')

    def path_env(name, default):
        path = Path(os.getenv(name, str(default))).expanduser()
        return (path if path.is_absolute() else ROOT / path).resolve()

    checkpoint = path_env('KNEE_AI_CHECKPOINT_PATH', ROOT / 'backend 2/ai/best_5slice_model.pth')
    required = [ROOT / 'backend 1/app/main.py', ROOT / 'frontend/code.html', checkpoint,
                path_env('KNEE_AI_MEMBER2_PATH', ROOT / 'member2_llm') / 'services/report_schema_validator.py',
                ROOT / 'demo_inputs/DICOM', ROOT / 'demo_inputs/ELIGIBLE_SERIES_MANIFEST.csv',
                ROOT / 'demo_inputs/DEMO_PATIENT_MRI_INFO.csv']
    for name in ('KNEE_AI_SERIES_METADATA_PATH',):
        if os.getenv(name):
            required.append(path_env(name, ROOT))
    for path in required:
        check(path.exists(), str(path), 'Restore the required file/directory or correct its environment override.')
    if args.hash and checkpoint.is_file():
        with checkpoint.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        check(digest == 'ac59d8ce17a0b35c15189d691f7c6aa828f31a3dfe14601a02036a6c3b892a82', 'checkpoint SHA-256', 'Restore the original frozen checkpoint; do not retrain.')
    url = os.getenv('KNEE_AI_DATABASE_URL', 'sqlite:///' + (ROOT / 'kneura_demo.db').as_posix())
    try:
        from sqlalchemy.engine import make_url
        parsed = make_url(url)
        if parsed.get_backend_name() != 'sqlite' or not parsed.database or parsed.database == ':memory:':
            raise ValueError('Prototype requires a persistent SQLite database URL.')
        db = Path(parsed.database).expanduser()
        db = (db if db.is_absolute() else ROOT / db).resolve()
        for directory in (db.parent, path_env('KNEE_AI_STUDY_ROOT', ROOT / '.prototype_data/uploads')):
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=directory):
                pass
        if db.exists():
            with db.open('r+b'):
                pass
        with tempfile.TemporaryFile():
            pass
        check(True, f'database/upload/temp writable: {db}', '')
    except Exception as exc:
        check(False, 'database/upload/temp paths', str(exc))
    if not args.skip_port:
        try:
            with socket.socket() as sock:
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                sock.bind(('127.0.0.1', args.port))
            check(True, f'port {args.port} available', '')
        except OSError:
            check(False, f'port {args.port} occupied/unavailable', f'Run Get-NetTCPConnection -LocalPort {args.port}; stop only your own server, or use -Port 8001.')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
