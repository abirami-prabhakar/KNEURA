"""Presentation checks with explicit failures, no secret values in responses."""
import os
from pathlib import Path
from . import narrative
from .demo_validation import verify_study


def check(service, full_model=False):
    result = {'backend': True, 'database': False, 'model': False, 'worker': False}
    try:
        with service.db() as conn:
            result['database'] = conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    except Exception:
        pass
    result['worker'] = bool(getattr(service.app.state, 'worker_ready', False))
    result['worker_mode'] = 'FastAPI background tasks; single API process; interrupted jobs fail safely on restart'
    try:
        from .inference import metadata, checkpoint_path, MODEL_LOCK
        result['model_metadata'] = metadata(service.DATA / 'checkpoints')
        if full_model:
            import torch
            torch.set_num_threads(max(1,min(4,os.cpu_count() or 1)))
            from knee_ai_inference import load_model
            with MODEL_LOCK:
                model = load_model(str(checkpoint_path(service.DATA / 'checkpoints')))
                with torch.no_grad():
                    output = model(torch.zeros(1,5,224,224))
                result['model'] = tuple(output.shape) == (1,12) and bool(torch.isfinite(output).all())
        result['model_check'] = 'Executed checkpoint' if full_model and result['model'] else 'File metadata only; run preflight with --model to execute checkpoint'
    except Exception:
        result['model_error'] = 'Checkpoint missing, incompatible or inference failed.'
    result['llm'] = narrative.health()
    root = Path(__file__).resolve().parents[1]
    try:
        result['demo_mri'] = verify_study(os.getenv('KNEURA_DEMO_MRI_DIR', root / 'demo_data/knee_mri'),
            os.getenv('KNEURA_SERIES_CSV', root / 'data/series_eligibility.csv'), os.getenv('KNEURA_DEMO_AUTHORIZATION'))
    except Exception:
        result['demo_mri'] = dict(ready=False, problems=['Study verification could not complete. Check configured files.'])
    result['configuration'] = dict(csv_required=os.getenv('KNEURA_REQUIRE_SERIES_CSV') == '1', secure_cookie=os.getenv('KNEURA_SECURE_COOKIE') == '1')
    result['finals_ready'] = all((result['database'], result['model'], result['worker'], result['llm']['reachable'], result['demo_mri']['ready'], result['configuration']['csv_required']))
    return result
