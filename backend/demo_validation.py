"""Demo metadata checks, not a substitute for authorized human de-identification review."""
import hashlib
import json
from pathlib import Path
import tempfile


def deidentification_issues(ds):
    issues = []
    if str(getattr(ds, 'PatientIdentityRemoved', '')).upper() != 'YES':
        issues.append('PatientIdentityRemoved must be YES')
    if not str(getattr(ds, 'DeidentificationMethod', '')).strip():
        issues.append('DeidentificationMethod is missing')
    if str(getattr(ds, 'BurnedInAnnotation', '')).upper() != 'NO':
        issues.append('BurnedInAnnotation must be NO; human pixel review still required')
    if str(getattr(ds, 'PatientName', '')).upper() not in ('', 'ANON', 'ANONYMOUS', 'DEIDENTIFIED'):
        issues.append('PatientName is not blank or an accepted anonymized label')
    for tag in ('PatientBirthDate', 'PatientAddress', 'PatientTelephoneNumbers', 'OtherPatientIDs', 'OtherPatientNames',
                'AccessionNumber', 'InstitutionName', 'InstitutionAddress', 'ReferringPhysicianName', 'PerformingPhysicianName', 'OperatorsName'):
        if str(getattr(ds, tag, '')).strip():
            issues.append(tag + ' must be removed for the controlled demo')
    if any(element.tag.is_private for element in ds.iterall()):
        issues.append('Private metadata remains')
    return issues


def verify_study(directory, csv_path, authorization_path=None):
    import pydicom
    from .ingestion import ingest
    directory, csv_path = Path(directory), Path(csv_path)
    files = sorted(p for p in directory.rglob('*') if p.is_file() and p.suffix.lower() in ('.dcm', '.dicom')) if directory.is_dir() else []
    result = dict(ready=False, synthetic=False, image_count=len(files), series=[], problems=[],
                  deidentification='Metadata checks only; authorization and pixel review must be attested separately.')
    if not files:
        result['problems'].append('No DICOM files supplied.')
        return result
    authorization = {}
    if authorization_path:
        try:
            authorization = json.loads(Path(authorization_path).read_text())
        except (OSError, ValueError):
            result['problems'].append('Authorization manifest could not be read.')
    hashes = {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    if not (authorization.get('authorized') is True and authorization.get('pixel_reviewed') is True and authorization.get('deidentified') is True and authorization.get('files') == hashes):
        result['problems'].append('An authorization/de-identification/pixel-review attestation matching the exact DICOM file hashes is required.')
    groups = {}
    for path in files:
        try:
            ds = pydicom.dcmread(path)
            if str(getattr(ds, 'ClinicalTrialProtocolName', '')) == 'KNEURA-SYNTHETIC-DEMO':
                result['synthetic'] = True
            issues = deidentification_issues(ds)
            result['problems'].extend(issues)
            key = str(ds.SeriesInstanceUID)
            group = groups.setdefault(key, dict(study_id=str(ds.StudyInstanceUID), series_id=key,
                modality=str(ds.Modality), sequence=str(getattr(ds, 'SeriesDescription', '')), dimensions=[], instance_numbers=[]))
            group['dimensions'].append([int(ds.Rows), int(ds.Columns)])
            group['instance_numbers'].append(int(ds.InstanceNumber))
        except Exception:
            result['problems'].append('A DICOM file could not be read or lacks required metadata.')
    result['series'] = list(groups.values())
    for group in result['series']:
        group['instance_numbers'].sort()
        group['image_count'] = len(group['instance_numbers'])
    if result['synthetic']:
        result['problems'].append('Synthetic input is not a clinical MRI demonstration.')
    if not csv_path.is_file():
        result['problems'].append('Series eligibility CSV missing.')
    else:
        try:
            # Use the exact ingestion/selection implementation, in temporary storage only.
            with tempfile.TemporaryDirectory(prefix='kneura-verify-') as temporary:
                payloads = [(p.name, p.read_bytes()) for p in files] + [('series.csv', csv_path.read_bytes())]
                _, selected = ingest(payloads, 'VERIFY', Path(temporary) / 'study')
                result['selected_series'] = [s['id'] for s in selected if s['eligible'] and len(s['images']) >= 5]
                result['windows'] = sum(max(0, len(s['images'])-4) for s in selected if s['eligible'])
                result['csv_sha256'] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
                if not result['selected_series']:
                    result['problems'].append('No CSV-selected series has five images.')
        except Exception as exc:
            result['problems'].append('Ingestion/selection validation failed: ' + str(exc))
    result['problems'] = list(dict.fromkeys(result['problems']))
    result['ready'] = not result['problems']
    return result
