"""Explicit local browser demo: real application/Model 1, mocked Gemini SDK only."""
import argparse
import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def generate_content(**kwargs):
    prompt = kwargs['contents']
    study_id = prompt.split('STUDY ID:\n', 1)[1].splitlines()[0]
    approved = ast.literal_eval(prompt.split('RADIOLOGIST-APPROVED FINDINGS:\n', 1)[1].splitlines()[0])
    assert approved and all(item['status'] == 'APPROVED' for item in approved)
    findings = [item['abnormality'] + '.' for item in approved]
    result = {
        'title': 'Knee MRI Report', 'study_id': study_id, 'status': 'DRAFT',
        'findings': findings, 'impression': ' '.join(findings),
        'note': 'MOCK PROVIDER — software demonstration only. Requires radiologist review and final approval.',
    }
    if 'patient-friendly explanation assistant' in prompt:
        names = [item['abnormality'] for item in approved]
        terms = {"MCL": "MCL is the ligament along the inner side of the knee.",
                 "Effusion": "Effusion means fluid in the knee joint."}
        result = {
            'title': 'Patient-Friendly MRI Explanation', 'study_id': study_id,
            'approved_findings': ', '.join(names),
            'what_this_means': ' '.join(terms.get(name, name + ' is listed in your approved report.') for name in names),
            'important_note': 'MOCK PROVIDER — demonstration only. This explanation is based on radiologist-approved information. Please discuss your MRI results with your doctor for clinical interpretation and next steps.',
        }
    return SimpleNamespace(text=json.dumps(result))


if __name__ == '__main__':
    import os
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    os.environ['GEMINI_API_KEY'] = 'explicit-local-mock-never-sent'
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    print('MOCK GEMINI PROVIDER ENABLED. Model 1 remains real. Live Gemini NOT TESTED.', flush=True)
    with patch('google.genai.Client', return_value=client):
        uvicorn.run('app.main:app', host='127.0.0.1', port=args.port)
