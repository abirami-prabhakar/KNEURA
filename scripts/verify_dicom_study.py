"""Inspect an explicitly supplied local demo; never acquires or modifies MRI."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.demo_validation import verify_study

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default='demo_data/knee_mri')
    parser.add_argument('--csv', default='data/series_eligibility.csv')
    parser.add_argument('--authorization')
    args = parser.parse_args()
    result = verify_study(args.directory, args.csv, args.authorization)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    sys.exit(0 if result['ready'] else 1)
