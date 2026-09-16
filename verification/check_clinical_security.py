import httpx, json
from pathlib import Path
BASE='http://127.0.0.1:8000'
UID='1.2.826.0.1.3680043.8.498.90283565381042081768587894596970552767'
c=httpx.Client(base_url=BASE, timeout=30)
evidence=[]
headers={}
for role,email in [('rad','radiologist'),('ortho','orthopedic'),('patient','patient')]:
    r=c.post('/login',json={'email':email+'@kneura.local','password':'Kneura-demo-74cP!2026'}); assert r.status_code==200,(role,r.text)
    headers[role]={'Authorization':'Bearer '+r.json()['access_token']}
    evidence.append(role+' login PASS')
for method,path,role,body,expected in [
 ('GET','/studies',None,None,401),
 ('GET','/studies','patient',None,403),
 ('GET','/studies/'+UID,'patient',None,403),
 ('GET','/reports/1/versions','patient',None,403),
 ('POST','/api/v1/ai/analyze','patient',{'study_id':UID,'action':'ANALYZE_KNEE_MRI'},403),
 ('PUT','/reports/1','ortho',{'draft_content':'unauthorized'},403),
 ('POST','/reports/1/approve','ortho',{},403),
 ('GET','/orthopedic/studies/'+UID,'ortho',None,409),
 ('POST','/studies/'+UID+'/patient-release','ortho',{},409),
 ('GET','/patient/reports/'+UID,'patient',None,409),
 ('POST','/studies/'+UID+'/patient-explanation','rad',{},409),
 ('GET','/studies/'+UID+'/mri-preview','patient',None,403),
]:
    r=c.request(method,path,headers=headers.get(role,{}),json=body)
    assert r.status_code==expected,(path,r.status_code,r.text)
    evidence.append(f'{role} {method} {path}: {expected}')
d=c.get('/studies/'+UID,headers=headers['rad']).json(); assert len(d['ai_probabilities'])==12
assert json.loads(d['report']['draft_content'])['final_approval']=='PENDING'
assert c.get('/patient/reports',headers=headers['patient']).json()==[]
Path('verification/clinical_security.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
print('PASS: all three accounts, Bearer/RBAC, preapproval and prerelease gates; existing DRAFT/PENDING and 12 probabilities preserved.')
