"""Adapter around the supplied, unchanged KNEE-AI 3.3 inference pipeline."""
import hashlib
import os
from pathlib import Path
import threading
import zipfile
import uuid
from .audit import now

ROOT = Path(__file__).resolve().parents[1]
MODEL_LOCK = threading.Lock()
CHECKPOINT_LOCK = threading.Lock()
NAMES = ['ACL', 'MCL', 'Medial Meniscus', 'Lateral Meniscus', 'Medial OA', 'Lateral OA', 'Patellofemoral OA', 'Effusion', 'Synovitis', "Baker's cyst", 'Contusion', 'Fracture']


def checkpoint_path(cache):
    with CHECKPOINT_LOCK:
        return _checkpoint_path(cache)


def _checkpoint_path(cache):
    configured = os.getenv('KNEURA_CHECKPOINT')
    if configured:
        path = Path(configured)
        if not path.is_file():
            raise RuntimeError('KNEURA_CHECKPOINT does not point to a checkpoint file.')
        return path
    source = ROOT / 'Model'
    if not (source / 'data.pkl').is_file():
        raise RuntimeError('The supplied Model directory is missing.')
    # Model/ is the extracted contents of a torch.save ZIP archive. Restore
    # archive structure without unpickling or changing a single tensor byte.
    files = sorted(p for p in source.rglob('*') if p.is_file())
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(source).as_posix().encode())
        digest.update(path.read_bytes())
    target = Path(cache) / ('knee-ai-' + digest.hexdigest()[:16] + '.pt')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix('.tmp')
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED) as archive:
            for path in files:
                archive.write(path, 'archive/' + path.relative_to(source).as_posix())
        temporary.replace(target)
    return target


def metadata(cache):
    path = checkpoint_path(cache)
    return dict(architecture='Learned 5→3 projection + EfficientNet-B0', version='KNEE-AI 3.3',
                checkpoint='SHA-256: ' + hashlib.sha256(path.read_bytes()).hexdigest(), outputs=12,
                input='5 consecutive slices · 224 × 224 · mean probability across all study windows',
                limitations='Research MVP. No clinically validated decision threshold. All 12 outputs require radiologist review. Grad-CAM is window-level model attribution, not a lesion segmentation.')


def analyze(case, directory, cache):
    import numpy as np
    import torch
    from PIL import Image
    from knee_ai_inference import load_model, create_windows, window_to_tensor
    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    with MODEL_LOCK:
        checkpoint = checkpoint_path(cache)
        checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        model = load_model(str(checkpoint), device='cpu')
        analysis_id, generated_at = uuid.uuid4().hex, now()
        predictions, windows = [], []
        for series in case['series']:
            if not series['eligible']:
                continue
            records = [{'path': str(directory / 'dicom' / (image['id'] + '.dcm')), 'InstanceNumber': image['instanceNumber']} for image in series['images']]
            for index, window in enumerate(create_windows(records)):
                x = window_to_tensor(window)
                with torch.no_grad():
                    probabilities = torch.sigmoid(model(x))[0].numpy()
                if probabilities.shape != (12,) or not np.isfinite(probabilities).all() or ((probabilities < 0) | (probabilities > 1)).any():
                    raise RuntimeError('Model returned invalid probabilities; no findings published.')
                predictions.append(probabilities)
                windows.append((series, index + 1, window))
        if not predictions:
            raise RuntimeError('No eligible five-slice windows. Supply series.csv with StudyInstanceUID, SeriesInstanceUID, Fluid_Sensitive and Fat_Suppression columns for the frozen series-selection policy.')
        values = np.asarray(predictions, dtype=np.float32)
        means = values.mean(axis=0)
        findings = []
        evidence_dir = directory / 'images'
        evidence_dir.mkdir(exist_ok=True)
        for class_index, name in enumerate(NAMES):
            # Representative evidence = highest scoring window for this class;
            # displayed study probability remains the frozen all-window mean.
            best = int(values[:, class_index].argmax())
            series, number, window = windows[best]
            x = window_to_tensor(window)
            activations = []
            def capture(_module, _inputs, output):
                activations.append(output)
            hook = model.backbone.features[-1].register_forward_hook(capture)
            try:
                logits = model(x)
                activation = activations[0]
                gradient = torch.autograd.grad(logits[0, class_index], activation)[0]
                cam = (gradient.mean(dim=(2, 3), keepdim=True) * activation).sum(dim=1).relu()
                cam = torch.nn.functional.interpolate(cam.unsqueeze(1), size=(224, 224), mode='bilinear', align_corners=False)[0, 0].detach().numpy()
                if not np.isfinite(cam).all():
                    raise RuntimeError('Grad-CAM returned non-finite values; no findings published.')
                cam = cam / cam.max() if cam.max() > 0 else cam
            finally:
                hook.remove()
            base = x[0, 0].numpy()
            rgb = np.repeat(base[..., None], 3, axis=2)
            heat = np.stack([cam, np.maximum(0, 1 - np.abs(cam - .5) * 2), 1 - cam], axis=-1)
            alpha = cam[..., None] * .45
            overlay = np.uint8(np.clip(rgb * (1 - alpha) + heat * alpha, 0, 1) * 255)
            finding_id = 'finding-' + str(class_index)
            Image.fromarray(overlay).save(evidence_dir / (finding_id + '.png'))
            np.save(evidence_dir / (finding_id + '.npy'), cam, allow_pickle=False)
            start, end = window[0]['InstanceNumber'], window[-1]['InstanceNumber']
            first = next(image for image in series['images'] if image['instanceNumber'] == start)
            findings.append(dict(id=finding_id, name=name, probability=float(means[class_index]), status='PENDING',
                patientExplanation=patient_explanation(name),
                evidence=dict(id=analysis_id + '-' + finding_id, analysisId=analysis_id, classIndex=class_index, generatedAt=generated_at, modelVersion='KNEE-AI 3.3', seriesId=series['id'], seriesName=series['name'], windowNumber=number,
                    sliceStart=start, sliceEnd=end, instanceNumbers=[record['InstanceNumber'] for record in window],
                    mriImageUrl=first['url'], gradCamImageUrl=f"/api/cases/{case['id']}/images/{finding_id}.png",
                    windowProbability=float(values[best, class_index]), attribution='Class-specific five-slice Grad-CAM overlaid on the first slice; not slice-localized evidence.')))
        return findings, dict(id=analysis_id, generatedAt=generated_at, seriesEvaluated=sum(bool(s['eligible']) for s in case['series']), windowsEvaluated=len(windows), aggregation='mean_probability_across_study_windows', modelVersion='KNEE-AI 3.3', checkpointSha256=checkpoint_hash)


def patient_explanation(name):
    descriptions = {
        'ACL': 'a stabilizing ligament inside your knee',
        'MCL': 'a stabilizing ligament on the inner side of your knee',
        'Medial Meniscus': 'the cushioning tissue on the inner side of your knee',
        'Lateral Meniscus': 'the cushioning tissue on the outer side of your knee',
        'Medial OA': 'arthritis-related changes on the inner side of your knee',
        'Lateral OA': 'arthritis-related changes on the outer side of your knee',
        'Patellofemoral OA': 'arthritis-related changes around your kneecap',
        'Effusion': 'fluid within your knee joint',
        'Synovitis': 'the lining of your knee joint',
        "Baker's cyst": 'a fluid-filled swelling behind your knee',
        'Contusion': 'a bruising-related change',
        'Fracture': 'a break or crack in a bone',
    }
    return f"Your radiologist approved a finding involving {descriptions[name]}. Your care team can explain what the finalized report means for you."
