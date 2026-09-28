"""Shared synthetic fixtures; never seed the user's workspace database."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend.app as backend


def seed_users():
    backend.init_db()
    with backend.db() as conn:
        for role in ('radiologist', 'orthopedist', 'patient'):
            salt = 'a1' * 16
            conn.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)',
                         (role, role + '@example.test', 'Test ' + role, role, salt,
                          backend.password_hash('test-password', salt), 'DEMO-SYNTHETIC'))


if __name__ == '__main__':
    import uvicorn
    backend.DATA = Path(sys.argv[1]).resolve()
    seed_users()
    from backend.demo import create_demo_package
    create_demo_package(backend.DATA / 'synthetic.zip')
    uvicorn.run(backend.app, host='127.0.0.1', port=int(sys.argv[2]), log_level='warning')

