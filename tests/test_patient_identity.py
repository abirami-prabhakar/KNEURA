"""Role projections must preserve the same saved patient identity without guessing age."""
from copy import deepcopy
import pytest
from backend.app import visible, authorized


@pytest.mark.parametrize('patient_id', ['', 'UNRELATED', 'P-IDENTITY'])
def test_shared_patient_access_still_requires_both_approvals(patient_id):
    case = {'status': 'FINAL', 'report': {'status': 'FINAL'}, 'releasedToPatient': True}
    account = {'role': 'patient', 'patient_id': patient_id}
    assert authorized(case, account)
    case['releasedToPatient'] = False
    assert not authorized(case, account)
    case['releasedToPatient'] = True
    case['report']['status'] = 'DRAFT'
    assert not authorized(case, account)
    case['report']['status'] = 'FINAL'
    case['status'] = 'REVIEWING'
    assert not authorized(case, account)

@pytest.mark.parametrize('age',[0,42,None])
def test_all_three_role_views_preserve_saved_demographics(age):
    patient={'name':'Identity Test','age':age,'gender':'Female'}
    case={'id':'KN-IDENTITY','status':'FINAL','study':{'id':'study','patientName':'DICOM name','patientId':'P-IDENTITY'},
          'patient':patient,'report':{'status':'FINAL','revisions':[]},'findings':[],'series':[], 'audit':[], 'releasedToPatient':True}
    original=deepcopy(case)
    for role in ('radiologist','orthopedist','patient'):
        result=visible(case,{'role':role,'patient_id':'P-IDENTITY'})
        assert result['patient']==patient
        assert result['id']==case['id']
    assert case==original
