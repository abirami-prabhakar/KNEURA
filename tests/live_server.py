"""Isolated browser-test server. Never seed the user's clinical database."""
import os
from pathlib import Path
import secrets
import sys
import shutil
import zipfile
import io

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as service
from backend.demo import create_demo_package

root = Path(os.environ['KNEURA_LIVE_DATA']).resolve()
workspace = Path(__file__).resolve().parents[1]
if root.parent != workspace / '.kneura' or not root.name.startswith('live-test-') or root.exists():
    raise RuntimeError('Browser tests require a NEW isolated .kneura/live-test-* directory.')
assert service.DATA.resolve() == root
service.init_db()
sample = os.getenv('KNEURA_LIVE_SAMPLE_ZIP')
patient_id = 'DEMO-SYNTHETIC'
if sample:
    import pydicom
    with zipfile.ZipFile(sample) as archive:
        ids = {str(pydicom.dcmread(io.BytesIO(archive.read(n)), stop_before_pixels=True).PatientID)
               for n in archive.namelist() if n.lower().endswith('.dcm')}
    if len(ids) != 1:
        raise ValueError('Sample must contain exactly one patient.')
    patient_id = ids.pop()
with service.db() as conn:
    for role in ('radiologist', 'orthopedist', 'patient', 'otherpatient'):
        salt = secrets.token_hex(16)
        conn.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)', (role, role + '@demo.test', 'DEMO ' + role,
            'patient' if role == 'otherpatient' else role, salt, service.password_hash(os.environ['KNEURA_LIVE_PASSWORD'], salt), patient_id if role == 'patient' else 'OTHER-PATIENT' if role == 'otherpatient' else ''))
if sample:
    shutil.copyfile(sample, root / 'demo.zip')
else:
    create_demo_package(root / 'demo.zip')

import uvicorn
uvicorn.run(service.app, host='127.0.0.1', port=8011)
