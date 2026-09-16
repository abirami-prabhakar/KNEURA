"""Register real demo input paths only; never create predictions or reviews."""
import argparse
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import pandas as pd
import pydicom
from app.database import Base, SessionLocal, engine
from app import models
from app.models.study import Study
from app.models.user import User


def load_demo_studies(data_root, case=1, all_studies=False):
    if engine.url.get_backend_name() != "sqlite" or not str(engine.url.database).endswith("kneura_demo.db"):
        raise SystemExit("Demo patient association requires an explicit SQLite database ending in kneura_demo.db.")
    data_root = Path(data_root).expanduser().resolve()
    manifest_path = data_root / "ELIGIBLE_SERIES_MANIFEST.csv"
    manifest = pd.read_csv(manifest_path)
    cases = pd.read_csv(data_root / "DEMO_PATIENT_MRI_INFO.csv")
    selected = cases if all_studies else cases[cases.Case == case]
    if selected.empty:
        raise SystemExit("No matching demo case.")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        patient = db.query(User).filter_by(email="patient@kneura.local", role="PATIENT").one_or_none()
        if patient is None:
            raise SystemExit("Run create_demo_users.py first.")
        for uid in selected.StudyInstanceUID:
            rows = manifest[(manifest.StudyInstanceUID == uid) & (manifest.Fluid_Sensitive == 1) & (manifest.Fat_Suppression == 1)]
            if rows.empty:
                raise SystemExit("Study has no eligible manifest series.")
            for series in rows.SeriesInstanceUID:
                directory = (data_root / "DICOM" / uid / series).resolve()
                if not directory.is_relative_to(data_root / "DICOM"):
                    raise SystemExit("Invalid manifest path.")
                files = list(directory.glob("*.dcm"))
                if len(files) < 5:
                    raise SystemExit("Eligible series needs at least five DICOM slices.")
                for path in files:
                    ds = pydicom.dcmread(path, stop_before_pixels=True)
                    if str(ds.StudyInstanceUID) != uid or str(ds.SeriesInstanceUID) != series or not hasattr(ds, "InstanceNumber"):
                        raise SystemExit("DICOM identity or slice ordering disagrees with manifest.")
            existing = db.query(Study).filter_by(study_id=uid).first()
            if existing:
                # Explicit setup also repairs paths after copying to a new laptop.
                # Never reset findings, reviews, ownership, or reports.
                existing.study_root = str(data_root / "DICOM")
                existing.series_metadata_path = str(manifest_path)
                continue
            db.add(Study(study_id=uid, patient_id=str(patient.id), data_mode="DEMO",
                         study_root=str(data_root / "DICOM"), series_metadata_path=str(manifest_path)))
        db.commit()
    print(f"Registered {len(selected)} real demo study/studies; existing records unchanged. Run inference and clinician review in the UI.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=BACKEND.parent / "demo_inputs")
    parser.add_argument("--case", type=int, default=1)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    load_demo_studies(args.data_root, args.case, args.all)
