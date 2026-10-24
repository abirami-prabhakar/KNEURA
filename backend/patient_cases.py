"""Patient-first case creation using the existing case JSON records and ingestion."""
import json
import shutil
import uuid
from typing import Literal
from starlette.concurrency import run_in_threadpool

from fastapi import Depends, File, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class PatientInformation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    patientName: str = Field(min_length=1, max_length=100)
    patientAge: int = Field(strict=True, ge=0, le=120)
    patientGender: Literal['Female', 'Male', 'Non-binary', 'Other', 'Prefer not to say']

    @field_validator('patientName', mode='before')
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


def install(api):
    # Keep the original multipart ingestion API for existing integration clients.
    api.app.router.routes[:] = [r for r in api.app.router.routes
                               if not (r.path == '/api/cases' and 'POST' in (getattr(r, 'methods', None) or set()))]

    def create_patient_case(body: PatientInformation, idempotency_key: str | None, account):
        timestamp = api.now()
        with api.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if idempotency_key:
                row = conn.execute("SELECT document FROM cases WHERE json_extract(document, '$.creationKey')=? AND json_extract(document, '$.createdBy')=?",
                                   (idempotency_key, account['id'])).fetchone()
                if row:
                    previous = json.loads(row['document'])
                    patient = previous['patient']
                    if (patient['name'], patient['age'], patient['gender']) != (body.patientName, body.patientAge, body.patientGender):
                        raise HTTPException(409, 'This submission was already used. Reopen New case to create another case.')
                    return api.visible(previous, account)
            case_id = 'KN-' + uuid.uuid4().hex[:12].upper()
            patient_id = 'P-' + uuid.uuid4().hex[:12].upper()
            case = dict(id=case_id,
                        study=dict(id=case_id, patientId=patient_id, patientName=body.patientName,
                                   description='Awaiting MRI upload', date=timestamp),
                        patient=dict(patient_id=patient_id, display_id=patient_id, name=body.patientName,
                                     age=body.patientAge, gender=body.patientGender,
                                     demographicsSource='Entered at case creation', enteredBy=account['id'], enteredAt=timestamp),
                        series=[], findings=[], audit=[], status='RECEIVED',
                        createdAt=timestamp, updatedAt=timestamp, createdBy=account['id'], creationKey=idempotency_key)
            api.event(case, 'CASE_CREATED: patient information recorded', account['name'], actor_id=account['id'], current='RECEIVED')
            api.validate_case_links(case)
            conn.execute('INSERT INTO cases (id, document) VALUES (?,?)', (case_id, json.dumps(case)))
        return api.visible(case, account)

    @api.app.post('/api/cases', status_code=201, openapi_extra={
        'requestBody': {'required': True, 'content': {'application/json': {'schema': PatientInformation.model_json_schema()}}}
    })
    async def create_case(request: Request, response: Response,
                          idempotency_key: str | None = Header(default=None, max_length=100),
                          account=Depends(api.radiologist)):
        if request.headers.get('content-type', '').startswith('multipart/form-data'):
            # Preserve the established one-step upload contract for existing clients.
            response.status_code = 200
            async with request.form(max_files=5000) as form:
                files = form.getlist('files')
                if not files or any(not hasattr(file, 'file') for file in files):
                    raise HTTPException(422, 'Select DICOM files to upload.')
                values = [form.get(key) for key in ('patient_name', 'patient_age', 'patient_gender')]
                if any(value is not None for value in values):
                    try:
                        raw_age = values[1]
                        if not isinstance(raw_age, str) or not raw_age.isdecimal():
                            raise ValueError('Invalid age')
                        patient = PatientInformation(patientName=values[0], patientAge=int(raw_age), patientGender=values[2])
                    except (ValidationError, ValueError):
                        raise HTTPException(422, 'Provide patient name, age (0-120), and gender.') from None
                    values = [patient.patientName, patient.patientAge, patient.patientGender]
                return await run_in_threadpool(api.upload, files, *values, account)
        try:
            body = PatientInformation.model_validate(await request.json())
        except (ValidationError, ValueError):
            raise HTTPException(422, 'Provide patient name, age (0-120), and gender.') from None
        return await run_in_threadpool(create_patient_case, body, idempotency_key, account)

    @api.app.post('/api/cases/{case_id}/study')
    def attach_study(case_id: str, files: list[UploadFile] = File(...), account=Depends(api.radiologist)):
        original = api.get_case(case_id)
        api.visible(original, account)
        if original['status'] != 'RECEIVED' or original['series'] or original.get('report'):
            raise HTTPException(409, 'This case already has a study or has entered review.')
        if not files or len(files) > 5000:
            raise HTTPException(422, 'Select between 1 and 5,000 DICOM files.')
        payloads, size = [], 0
        for file in files:
            data = file.file.read(api.MAX_BYTES - size + 1)
            size += len(data)
            if size > api.MAX_BYTES:
                raise HTTPException(413, 'Study uploads are limited to 512 MB.')
            payloads.append((file.filename or 'image.dcm', data))
        root = (api.DATA / 'studies').resolve()
        root.mkdir(parents=True, exist_ok=True)
        destination = (root / case_id).resolve()
        staging = (root / ('upload-' + uuid.uuid4().hex)).resolve()
        if destination.parent != root or staging.parent != root:
            raise HTTPException(400, 'Invalid case reference.')
        moved = False
        try:
            study, series = api.ingest(payloads, case_id, staging)
            # DICOM metadata remains separate from the manually entered demographics.
            study['patientName'] = original['patient']['name']
            dicom_age = study.pop('patientAge', None)
            dicom_sex = study.pop('patientSex', None)
            with api.db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                row = conn.execute('SELECT document FROM cases WHERE id=?', (case_id,)).fetchone()
                current = json.loads(row['document']) if row else None
                if current != original or destination.exists():
                    raise HTTPException(409, 'The case changed during upload. Refresh before trying again.')
                current['study'] = study
                current['series'] = series
                current['patient']['dicomPatientId'] = study['patientId']
                current['patient']['dicomAge'] = dicom_age
                current['patient']['sex'] = dicom_sex
                current['updatedAt'] = api.now()
                api.event(current, 'MRI received and DICOM images validated', account['name'], actor_id=account['id'], current='RECEIVED')
                api.event(current, f"Series selection: {sum(bool(s.get('eligible')) for s in series)} eligible of {len(series)} series", 'KNEE-AI ingestion')
                api.validate_case_links(current)
                staging.rename(destination)
                moved = True
                conn.execute('UPDATE cases SET document=? WHERE id=?', (json.dumps(current), case_id))
            return api.visible(current, account)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(422, 'The DICOM study could not be validated. Check the files and series eligibility CSV.') from exc
        except Exception as exc:
            # No patient metadata, uploaded filenames, or raw exceptions in logs/responses.
            api.LOG.error('Study attachment failed (%s)', type(exc).__name__)
            raise HTTPException(500, 'Unable to attach the study. Please try again.') from exc
        finally:
            if staging.exists():
                shutil.rmtree(staging)
            # A failed database commit must not strand the case with an attached folder.
            if moved:
                saved = api.get_case(case_id)
                if not saved['series'] and destination.exists():
                    shutil.rmtree(destination)

    api.app.openapi_schema = None
