import os, sqlite3, sys
from pathlib import Path
root=Path.cwd()
target=root/'verification/approval_gate_test.db'
with sqlite3.connect('verification/before_clinical_journey.db') as source, sqlite3.connect(target) as dest: source.backup(dest)
os.environ['KNEE_AI_DATABASE_URL']='sqlite:///'+target.as_posix()
sys.path.insert(0,str(root/'backend 1'))
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.radiologist_review import ValidatedFinding, RadiologistReview
uid='1.2.826.0.1.3680043.8.498.90283565381042081768587894596970552767'
with SessionLocal() as db:
 review=db.query(RadiologistReview).filter_by(study_id=uid).order_by(RadiologistReview.id.desc()).first()
 db.query(ValidatedFinding).filter_by(review_id=review.id,finding='ACL').delete(); db.commit()
with TestClient(app) as c:
 token=c.post('/login',json={'email':'radiologist@kneura.local','password':'Kneura-demo-74cP!2026'}).json()['access_token']
 r=c.post('/reports/1/approve',headers={'Authorization':'Bearer '+token})
 assert r.status_code==409,r.text
 print('PASS incomplete finding review blocks approval (isolated database only)')
