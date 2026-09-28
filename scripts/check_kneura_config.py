"""Check the existing adapter's process configuration without exposing credentials.

The PowerShell launcher loads the private backend env file before running Python.
--health makes a real provider request using the unchanged adapter health contract.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import narrative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--health', action='store_true')
    args = parser.parse_args()
    try:
        config = narrative.configuration()
    except (TypeError, ValueError):
        print(json.dumps({'configured': False, 'error': 'Invalid numeric LLM configuration.'}))
        return 1
    if args.health:
        result = narrative.health()
        success = result.get('configured') and result.get('reachable')
    else:
        result = {name: config[name] for name in ('configured', 'provider', 'model')}
        result['credential_present'] = bool(config['key'])
        if not config['configured']:
            result['error'] = 'Set a full KNEURA_LLM_URL and exact KNEURA_LLM_MODEL before startup.'
        success = config['configured']
    # Do not print URLs, credentials, request headers or exception bodies.
    print(json.dumps(result, indent=2))
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
