import argparse
import json
from pathlib import Path
import sys
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as service
from backend.readiness import check

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Presentation-machine readiness. Missing dependencies cause a nonzero exit.')
    parser.add_argument('--model', action='store_true', help='Actually load and execute the supplied checkpoint.')
    parser.add_argument('--api', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    service.init_db()
    result = check(service, args.model)
    try:
        with urllib.request.urlopen(args.api.rstrip('/') + '/api/health', timeout=5) as response:
            server = json.load(response)
            result['backend'] = server.get('status') == 'ok'
            result['worker'] = server.get('worker_ready', False)
    except Exception:
        result['backend'] = False
    result['finals_ready'] = all((result['backend'],result['database'],result['model'],result['worker'],result['llm']['reachable'],result['demo_mri']['ready'],result['configuration']['csv_required']))
    print(json.dumps(result, indent=2, ensure_ascii=True))
    sys.exit(0 if result['finals_ready'] else 1)
