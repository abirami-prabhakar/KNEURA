# Clean deployment source

This release starts with fresh Git history to exclude historical runtime data.
Local databases, scans, caches, test output, supplied scan overlays, eligibility data and model weights are intentionally excluded. Tests and application source remain included.

Provision the trusted checkpoint separately on the server and set KNEURA_CHECKPOINT to its absolute path. The original local Model directory and .kneura/checkpoints files remain untouched. Store runtime data outside the release and set KNEURA_DATA_DIR. Do not commit provider credentials.

Supplied reference scan overlays are not distributed in this release. Live study images continue to come from the authenticated backend. Supply an authorized series eligibility CSV separately if enabling KNEURA_REQUIRE_SERIES_CSV.

Build with npm ci and npm run build. Run the Linux backend with python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1 after installing backend/requirements.txt in a virtual environment. Configure HTTPS, origins, secrets and persistent storage before deployment. See UBUNTU_DEPLOYMENT.md for the Linux service and updated test contract. These changes do not certify AWS readiness.
