import httpx,json,sqlite3,os
from pathlib import Path
uid='1.2.826.0.1.3680043.8.498.90283565381042081768587894596970552767'
c=httpx.Client(base_url='http://127.0.0.1:8000',timeout=30)
h={}
for role,email in [('rad','radiologist'),('ortho','orthopedic'),('patient','patient')]:
 r=c.post('/login',json={'email':email+'@kneura.local','password':'Kneura-demo-74cP!2026'}); r.raise_for_status(); h[role]={'Authorization':'Bearer '+r.json()['access_token']}
d=c.get('/studies/'+uid,headers=h['rad']).json(); assert d['workflow_state']=='PATIENT_RELEASED'
assert len(d['ai_probabilities'])==12
report=d['report']; signed=json.loads(report['draft_content']); assert report['status']==signed['status']==signed['final_approval']=='APPROVED'
assert report['current_version']==report['approved_version']==2
versions=c.get('/reports/1/versions',headers=h['rad']).json(); assert len(versions)==2 and versions[0]['status']=='DRAFT' and versions[1]['status']=='APPROVED'
assert json.loads(versions[0]['content'])['final_approval']=='PENDING'
assert signed['findings']==['MCL.','Effusion.']
for role,code in [('rad',409),('ortho',403),('patient',403)]:
 r=c.put('/reports/1',headers=h[role],json={'draft_content':'forbidden edit'}); assert r.status_code==code,(role,r.text)
assert c.post('/studies/'+uid+'/patient-explanation',headers=h['rad']).status_code==409
patient=c.get('/patient/reports/'+uid,headers=h['patient']).json()
assert patient['status']=='RELEASED' and patient['patient_explanation']['approved_findings']=='MCL, Effusion'
assert 'MOCK PROVIDER' in patient['patient_explanation']['important_note']
for secret in ['ai_probabilities','confidence','validated_findings','INTERNAL DEMO NOTE','MCL changes reviewed','REJECTED','PENDING','audit_logs']:
 assert secret not in json.dumps(patient),secret
assert c.get('/studies/'+uid,headers=h['patient']).status_code==403
assert c.get('/studies/'+uid+'/mri-preview',headers=h['patient']).status_code==403
assert c.get('/health').status_code==200
with sqlite3.connect('kneura_demo.db') as db, sqlite3.connect('verification/before_clinical_journey.db') as before:
 sql='select label,confidence from predictions where study_id=? order by label'
 assert db.execute(sql,(uid,)).fetchall()==before.execute(sql,(uid,)).fetchall()
 audit=[r[0] for r in db.execute('select action from audit_logs where study_id=? order by id',(uid,))]
 for action in ['REPORT_EDITED','REPORT_APPROVED','ORTHOPEDIC_REVIEW_SUBMITTED','PATIENT_RELEASED','PATIENT_EXPLANATION_GENERATED','STUDY_VIEWED']:
  assert action in audit,action
result={'result':'PASS','study_id':uid,'workflow':'PATIENT_RELEASED','model_probabilities_unchanged':True,'report_versions':len(versions),'signed_version':2,'rbac':'PASS','patient_internal_data_exclusion':'PASS','audit_actions':audit,'live_gemini':'NOT TESTED' if not os.getenv('GEMINI_API_KEY') else 'KEY AVAILABLE'}
Path('verification/clinical_journey.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
