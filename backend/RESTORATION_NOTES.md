# Backend restoration notes

The original Python source was not found. `backend/app.py` and missing sibling modules were restored as minimal loaders for the original Python 3.14 `.pyc` files. The loaders do not reimplement routes or model behavior; they execute the compiled KNEURA modules unchanged.

The app loader uses `.kneura/recovery/app-original.cpython-314.pyc` so importing the wrapper cannot overwrite the protected original cache entry. Runtime must set `PYTHONDONTWRITEBYTECODE=1` for this recovery mode. The original `backend/__pycache__/app.cpython-314.pyc` remains SHA-256 `46C195B612016C3D6136D12113E6780AA29EC327E91425B446207D9229CD94CD`.

Missing source sibling modules restored with the same mechanism: `auth`, `audit`, `demo`, `demo_validation`, `inference`, `ingestion`, `narrative`, `readiness`, `recovery`, `relationships`, `reporting`, and `report_jobs`. `viewer.py` was already present as a recovered source module. The frozen root `knee_ai_inference.py` was restored byte-for-byte from the handoff ZIP and remains SHA-256 `4A86A64ABA740089F03C2A169C89D8F612731BD43E45591963532E191D27A677`.

This is a bytecode execution bridge, not a source decompilation. Replace it with reviewed original source if that source is later recovered.
