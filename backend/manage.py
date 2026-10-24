"""Explicit local account provisioning and orthopedist case assignment."""
import argparse
import getpass
import secrets
import uuid
from .app import db, init_db, password_hash, get_case, event, save_case, LOCK


def main():
    parser = argparse.ArgumentParser(description='Manage local KNEURA MVP users')
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create-user')
    create.add_argument('--email', required=True)
    create.add_argument('--name', required=True)
    create.add_argument('--role', required=True, choices=['radiologist', 'orthopedist', 'patient'])
    create.add_argument('--patient-id', default='', help='Legacy metadata; not required for Patient Coordinators (role patient).')
    grant = sub.add_parser('assign')
    grant.add_argument('--email', required=True)
    grant.add_argument('--case', required=True)
    sub.add_parser('check-model')
    args = parser.parse_args()
    init_db()
    if args.command == 'create-user':
        password = getpass.getpass('New password (at least 12 characters): ')
        if len(password) < 12:
            parser.error('Password must contain at least 12 characters.')
        salt = secrets.token_hex(16)
        with db() as conn:
            conn.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)',
                         (uuid.uuid4().hex, args.email.strip().lower(), args.name, args.role, salt, password_hash(password, salt), args.patient_id))
        print('Account created. Sign in through the KNEURA UI.')
    elif args.command == 'assign':
        get_case(args.case)
        with db() as conn:
            account = conn.execute('SELECT id,role FROM users WHERE email=?', (args.email.lower().strip(),)).fetchone()
            if not account or account['role'] != 'orthopedist':
                parser.error('Assignment requires an existing orthopedist account.')
            conn.execute('INSERT OR IGNORE INTO grants VALUES (?,?)', (args.case, account['id']))
        with LOCK:
            case = get_case(args.case)
            event(case, 'Orthopedist access assigned to ' + args.email.lower().strip(), 'Local account administrator')
            save_case(case)
        print('Case assigned. It becomes visible after final approval.')
    else:
        import torch
        from knee_ai_inference import load_model
        from .inference import checkpoint_path, metadata
        from .app import DATA
        model = load_model(str(checkpoint_path(DATA / 'checkpoints')))
        with torch.no_grad():
            output = model(torch.zeros(1, 5, 224, 224))
        assert output.shape == (1, 12) and torch.isfinite(output).all()
        import json
        print(json.dumps(metadata(DATA / 'checkpoints'), ensure_ascii=True))
        print('Checkpoint loaded strictly; finite 12-output inference passed.')


if __name__ == '__main__':
    main()
