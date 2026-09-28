"""Validated single-study DICOM ingestion; filenames never become storage paths."""
import os
import hashlib
import csv
import io
from pathlib import Path
import re
import uuid
import zipfile

MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 5000


def ingest(payloads, case_id, directory):
    import numpy as np
    import pydicom
    from PIL import Image
    from knee_ai_inference import preprocess_dicom
    payloads = list(payloads)
    entries, size = [], 0
    for name, data in payloads:
        if name.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = [i for i in archive.infolist() if not i.is_dir()]
                if len(infos) + len(entries) > MAX_FILES or sum(i.file_size for i in infos) + size > MAX_BYTES:
                    raise ValueError('Study package exceeds 512 MB or 5,000 files.')
                for info in infos:
                    entries.append((info.filename, archive.read(info)))
                    size += info.file_size
        else:
            entries.append((name, data))
            size += len(data)
        if size > MAX_BYTES or len(entries) > MAX_FILES:
            raise ValueError('Study package exceeds 512 MB or 5,000 files.')
    configured_csv = os.getenv('KNEURA_SERIES_CSV')
    if configured_csv and not any(name.lower().endswith('.csv') for name, _ in entries):
        entries.append(('configured-series.csv', Path(configured_csv).read_bytes()))
    flags, records, has_csv = {}, [], False
    csv_hashes = []
    for name, data in entries:
        if name.lower().endswith('.csv'):
            has_csv = True
            csv_hashes.append(hashlib.sha256(data).hexdigest())
            reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
            columns = {'StudyInstanceUID', 'SeriesInstanceUID', 'Fluid_Sensitive', 'Fat_Suppression'}
            if not columns.issubset(reader.fieldnames or []):
                raise ValueError('Series CSV requires StudyInstanceUID, SeriesInstanceUID, Fluid_Sensitive, Fat_Suppression.')
            for row in reader:
                if row['Fluid_Sensitive'] not in ('0', '1') or row['Fat_Suppression'] not in ('0', '1'):
                    raise ValueError('Series eligibility flags must be 0 or 1.')
                key = (row['StudyInstanceUID'], row['SeriesInstanceUID'])
                if key in flags:
                    raise ValueError('Series CSV contains duplicate series.')
                flags[key] = row['Fluid_Sensitive'] == '1' and row['Fat_Suppression'] == '1'
            continue
        if Path(name).name.startswith('.') or '__MACOSX' in name:
            continue
        try:
            ds = pydicom.dcmread(io.BytesIO(data))
        except pydicom.errors.InvalidDicomError:
            raise ValueError(f'Not a valid DICOM file: {Path(name).name}') from None
        if str(getattr(ds, 'Modality', '')) != 'MR':
            raise ValueError('Only MR DICOM instances are supported.')
        required = ['StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID', 'InstanceNumber']
        if any(not hasattr(ds, key) for key in required):
            raise ValueError('Every image requires study, series, SOP UID and InstanceNumber.')
        if int(getattr(ds, 'NumberOfFrames', 1)) != 1 or int(getattr(ds, 'SamplesPerPixel', 1)) != 1:
            raise ValueError('The frozen pipeline supports single-frame grayscale MRI only.')
        if int(getattr(ds, 'Rows', 0)) * int(getattr(ds, 'Columns', 0)) > 4096 * 4096:
            raise ValueError('DICOM image dimensions exceed the supported limit.')
        records.append((ds, data))
    if os.getenv('KNEURA_REQUIRE_SERIES_CSV') == '1' and not has_csv:
        raise ValueError('This demo requires an explicit series eligibility CSV. No heuristic fallback is allowed.')
    if not records:
        raise ValueError('No MRI DICOM images were found.')
    studies = {str(ds.StudyInstanceUID) for ds, _ in records}
    patients = {str(getattr(ds, 'PatientID', '')) for ds, _ in records}
    if len(studies) != 1 or len(patients) != 1:
        raise ValueError('Upload exactly one study for one patient at a time.')
    if not next(iter(patients)).strip():
        raise ValueError('PatientID is required to associate the study with a patient. Use a consistent pseudonymous ID for de-identified studies.')
    if any(not str(getattr(ds, key)).strip() for ds, _ in records for key in ('StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID')):
        raise ValueError('Study, series and SOP UIDs cannot be blank.')
    if os.getenv('KNEURA_REQUIRE_SERIES_CSV') == '1' and any((str(ds.StudyInstanceUID), str(ds.SeriesInstanceUID)) not in flags for ds, _ in records):
        raise ValueError('Required eligibility CSV must explicitly classify every uploaded series.')
    first = records[0][0]
    series, seen_sop, seen_instance = {}, set(), set()
    (directory / 'dicom').mkdir(parents=True)
    (directory / 'images').mkdir()
    for ds, data in records:
        uid = str(ds.SeriesInstanceUID)
        instance = int(ds.InstanceNumber)
        if str(ds.SOPInstanceUID) in seen_sop or (uid, instance) in seen_instance:
            raise ValueError('Duplicate SOP UID or InstanceNumber within a series.')
        seen_sop.add(str(ds.SOPInstanceUID))
        seen_instance.add((uid, instance))
        if uid not in series:
            description = str(getattr(ds, 'SeriesDescription', uid))
            sequence = str(getattr(ds, 'SequenceName', ''))
            # Conservative metadata fallback. CSV flags are authoritative and
            # reproduce the supplied pipeline's Fluid_Sensitive & Fat_Suppression filter.
            text = (description + ' ' + sequence).upper()
            fluid = bool(re.search(r'\b(T2|PD|STIR|TIRM)\b', text))
            fat = bool(re.search(r'\b(FS|FATSAT|FAT SAT|FAT SUPPRESSED|STIR|TIRM|SPAIR|SPIR)\b', text))
            key = (str(ds.StudyInstanceUID), uid)
            eligible = flags.get(key, fluid and fat) if not has_csv else flags.get(key, False)
            series[uid] = dict(id=uid, name=description, sequence=sequence or description, images=[], eligible=eligible,
                selectionSource='Uploaded CSV flags' if has_csv else 'DICOM description heuristic; confirm against acquisition metadata')
        if has_csv:
            series[uid]['eligibilityCsvSha256'] = csv_hashes
        image_id = uuid.uuid4().hex
        target = directory / 'dicom' / (image_id + '.dcm')
        target.write_bytes(data)
        try:
            pixels = preprocess_dicom(str(target)).numpy()
        except Exception as exc:
            raise ValueError('DICOM pixels could not be decoded. Install the appropriate pydicom transfer-syntax decoder.') from exc
        Image.fromarray(np.uint8(pixels * 255)).save(directory / 'images' / (image_id + '.png'))
        from .viewer import display_metadata
        display = display_metadata(target)
        series[uid]['images'].append(dict(id=image_id, instanceNumber=instance, url=f'/api/cases/{case_id}/images/{image_id}.png', sourceUrl=f'/api/cases/{case_id}/source-images/{image_id}', **display))
    for value in series.values():
        value['images'].sort(key=lambda image: image['instanceNumber'])
    date = str(getattr(first, 'StudyDate', ''))
    return dict(id=str(first.StudyInstanceUID), patientName=str(getattr(first, 'PatientName', 'Unnamed')).replace('^', ' '),
                patientId=str(first.PatientID), patientAge=str(getattr(first, 'PatientAge', '')), patientSex=str(getattr(first, 'PatientSex', '')), description=str(getattr(first, 'StudyDescription', 'Knee MRI')),
                demonstration=str(getattr(first, 'ClinicalTrialProtocolName', '')) == 'KNEURA-SYNTHETIC-DEMO',
                date=f'{date[:4]}-{date[4:6]}-{date[6:8]}' if len(date) == 8 else '',
                laterality=str(getattr(first, 'ImageLaterality', getattr(first, 'Laterality', '')))), list(series.values())
