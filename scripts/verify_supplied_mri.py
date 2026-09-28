"""Observe the existing pipeline without changing model or Grad-CAM computations."""
import hashlib
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pydicom
import torch
import knee_ai_inference as frozen
from backend import inference
from backend.demo_validation import deidentification_issues
from backend.ingestion import ingest


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = Path(sys.argv[1]).resolve()
    files = sorted(source.glob('*.dcm'))
    if not files:
        raise ValueError('Expected an extracted directory containing actual DICOM files.')
    out = Path('.kneura') / ('m1-verification-' + uuid.uuid4().hex)
    artifacts = [Path('knee_ai_inference.py'), Path('backend/inference.py')]
    before = {str(p): sha(p) for p in artifacts}
    _, series = ingest([(p.name, p.read_bytes()) for p in files], 'VERIFY-M1', out)
    calls, models, handles = [], [], []
    original = frozen.load_model

    def observed_loader(path, device='cpu'):
        model = original(path, device)
        models.append(model)
        def observe(_model, inputs, output):
            x = inputs[0].detach().clone()
            calls.append((x, torch.sigmoid(output.detach())[0].numpy().copy(), torch.is_grad_enabled()))
        handles.append(model.register_forward_hook(observe))
        return model

    frozen.load_model = observed_loader
    try:
        findings, analysis = inference.analyze({'id': 'VERIFY-M1', 'series': series}, out, Path('.kneura/checkpoints'))
    finally:
        frozen.load_model = original
        for handle in handles:
            handle.remove()
    count = analysis['windowsEvaluated']
    assert len(calls) == count + 12
    probabilities = np.stack([item[1] for item in calls[:count]])
    np.testing.assert_array_equal(probabilities.mean(axis=0), np.array([f['probability'] for f in findings], dtype=np.float32))
    checks = []
    for index, finding in enumerate(findings):
        best = int(probabilities[:, index].argmax())
        x, probability, grad_enabled = calls[count + index]
        assert grad_enabled and torch.equal(x, calls[best][0])
        np.testing.assert_array_equal(probability, probabilities[best])
        with torch.no_grad():
            after = torch.sigmoid(models[0](x))[0].numpy()
        np.testing.assert_array_equal(after, probabilities[best])
        evidence = finding['evidence']
        selected = next(s for s in series if s['id'] == evidence['seriesId'])
        expected = selected['images'][evidence['windowNumber']-1:evidence['windowNumber']+4]
        assert evidence['instanceNumbers'] == [i['instanceNumber'] for i in expected]
        assert evidence['mriImageUrl'] == expected[0]['url']
        cam = np.load(out / 'images' / (finding['id'] + '.npy'))
        assert cam.shape == (224, 224) and np.isfinite(cam).all()
        assert (out / 'images' / (finding['id'] + '.png')).is_file()
        checks.append(dict(finding=finding['name'], probability=finding['probability'], evidence=evidence,
            tensor_identical=True, probabilities_unchanged=True, heatmap_min=float(cam.min()), heatmap_max=float(cam.max())))
    assert before == {str(p): sha(p) for p in artifacts}
    datasets = [pydicom.dcmread(p, stop_before_pixels=True) for p in files]
    report = dict(status='PASS: technical inference and existing Grad-CAM', source=str(source), dicom_count=len(files),
        provenance='PROVENANCE VERIFICATION REQUIRED', metadata_issues=sorted({v for d in datasets for v in deidentification_issues(d)}),
        checkpoint=str(inference.checkpoint_path(Path('.kneura/checkpoints')).resolve()), analysis=analysis,
        series=[dict(uid=s['id'], selected=s['eligible'], reason=s['selectionSource'], instances=[i['instanceNumber'] for i in s['images']]) for s in series],
        csv_status='Authoritative per-series CSV missing; existing metadata heuristic used for technical testing only.',
        target_layer='model.backbone.features[-1]', target_layer_type=type(models[0].backbone.features[-1]).__name__,
        frozen_hashes=before, findings=checks)
    (out / 'verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print('SAVED', (out / 'verification.json').resolve())


if __name__ == '__main__':
    main()
