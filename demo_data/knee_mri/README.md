# Authorized clinical demo input

No clinical MRI was supplied. Put only authorized, de-identified `.dcm` files here;
the directory's imaging files are excluded from Git. Do not copy patient identifiers
or the synthetic noise dataset here and call it clinical MRI.

Populate `data/series_eligibility.csv` with the actual study/series UIDs and reviewed
Fluid_Sensitive/Fat_Suppression flags (0 or 1). The header-only file intentionally
selects nothing. No reference-case UIDs are invented as actual input.

Use a local authorization JSON with `authorized`, `deidentified`, and `pixel_reviewed`
set to true only after the responsible data owner confirms them. Include `files`, a
map of relative DICOM filenames to their SHA-256 hashes. Do not include patient names.
This is an attestation, not automatic proof of legal authorization or complete de-identification.

Run `python scripts/verify_dicom_study.py --authorization path/to/authorization.json`.
The utility checks required metadata, metadata de-identification flags, pixel decoding,
dimensions, InstanceNumbers, the exact ingestion policy and eligible five-slice windows.
It cannot independently detect every identifier or burned-in annotation; human pixel
review remains required. It does not edit the input files.

For the presentation set `KNEURA_REQUIRE_SERIES_CSV=1`,
`KNEURA_SERIES_CSV=data/series_eligibility.csv`, `KNEURA_DEMO_MRI_DIR=demo_data/knee_mri`
and `KNEURA_DEMO_AUTHORIZATION=path/to/authorization.json` in the backend environment.
