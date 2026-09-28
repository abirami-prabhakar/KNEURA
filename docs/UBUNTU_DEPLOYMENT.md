# Ubuntu service setup

Use the `release-clean` source. The service runs one API process, including the report worker, as a dedicated user. It binds only to localhost; use Caddy for HTTPS. Do not run `npm run api` on Ubuntu (that is the Windows configuration loader). For manual Linux startup use `npm run api:linux` with environment variables already exported. The systemd service loads its own environment file.

## Prepare the host

On Ubuntu 24.04 x86-64, install Python and clone or transfer the clean release into `/opt/kneura/app`. Install a Node version satisfying package-lock.json before building the frontend (or transfer a locally built `dist/`). Do not copy the workstation database or scans.

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip git
sudo useradd --system --user-group --home-dir /var/lib/kneura --shell /usr/sbin/nologin kneura
sudo install -d -m 0755 /opt/kneura /opt/kneura/model
sudo install -d -m 0700 /etc/kneura
sudo install -d -o kneura -g kneura -m 0700 /var/lib/kneura
sudo install -d -o "$(id -un)" -g "$(id -gn)" -m 0755 /opt/kneura/app
git clone --branch release-clean --single-branch https://github.com/abirami-prabhakar/KNEURA.git /opt/kneura/app
sudo python3 -m venv /opt/kneura/venv
sudo /opt/kneura/venv/bin/python -m pip install -r /opt/kneura/app/backend/requirements.txt
```

For a private repository, authenticate Git before cloning; do not embed a token in the URL. Run the account/directory creation once. Dependencies are currently ranged rather than a verified Linux lockfile; resolve and test on the target host before release.

Transfer the trusted checkpoint separately to `/opt/kneura/model/checkpoint.pt`, verify its SHA-256 against the source copy, then set root ownership and mode 0644. This file must be readable by kneura but must not be inside the publicly served frontend directory. Model loading is tested separately below.

## Configure and start

```bash
cd /opt/kneura/app
sudo install -m 0600 deploy/kneura.env.example /etc/kneura/kneura.env
sudoedit /etc/kneura/kneura.env
sudo install -m 0644 deploy/kneura.service /etc/systemd/system/kneura.service
sudo systemd-analyze verify /etc/systemd/system/kneura.service
sudo systemctl daemon-reload
sudo systemctl enable --now kneura
sudo systemctl status kneura --no-pager
curl --fail http://127.0.0.1:8000/api/health
sudo journalctl -u kneura -n 100 --no-pager
```

Replace the domain and every placeholder in the environment file. Use the provider endpoint and model approved for your account; the file contains examples, not working credentials. `ExecStartPre` checks configuration presence, not remote provider availability. Never commit the edited environment file. systemd loads EnvironmentFile itself; do not source this file as shell code.

`StateDirectory` keeps runtime data at `/var/lib/kneura` with private permissions across service restarts; it does not provide backups. `ProtectSystem=strict` makes application/model files read-only to the service while the state directory remains writable. See the [systemd execution reference](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml).

Check the model and create the first account using the same runtime paths:

```bash
cd /opt/kneura/app
sudo -u kneura env KNEURA_DATA_DIR=/var/lib/kneura KNEURA_CHECKPOINT=/opt/kneura/model/checkpoint.pt /opt/kneura/venv/bin/python -B -m backend.manage check-model
sudo -u kneura env KNEURA_DATA_DIR=/var/lib/kneura /opt/kneura/venv/bin/python -B -m backend.manage create-user --email YOUR_EMAIL --name YOUR_NAME --role radiologist
```

The user-management command prompts privately for a password. Patients need an exact DICOM PatientID; account creation does not automatically release reports.

## Frontend and HTTPS

Build the clean source with `npm ci` followed by `npm run build` as your deployment user. Serve only `dist/`, never `/opt/kneura/app` or `/var/lib/kneura`. Install Caddy and adapt `deploy/Caddyfile.example`: replace `{$KNEURA_HOST}` with your domain and `{$KNEURA_DIST}` with `/opt/kneura/app/dist`, or provide these variables to the Caddy service. Point DNS at the instance, validate the Caddy config, then enable HTTPS. Allow 80/443 in the AWS security group; restrict administrative access and keep 8000/5173 private.

Secure session cookies require HTTPS for browser login. The configured origin must exactly match the browser's origin. Test the public `/api/health` path and login through Caddy, not the Vite development server.

## Release verification

Run `python -m pytest tests -q` with KNEURA_CHECKPOINT pointing at the separately provisioned model. Tests generate synthetic studies; no clinical scans are needed. Run `npm test`, `npm run build`, `npm run lint`, and `npm run test:e2e` (install Playwright Chromium with `npx playwright install chromium` first). The real-checkpoint test intentionally fails if no checkpoint is provisioned.

The supported creation API is a single multipart POST `/api/cases` with files and optional complete demographics (`patient_name`, `patient_age`, `patient_gender`). JSON-only draft creation, separate `/study` attachment and creation-idempotency keys are not implemented. Do not automatically retry an upload after an uncertain network result without checking the worklist. Existing integration clients may send DICOM-only multipart uploads.

Before public release, exercise synthetic upload, real inference, actual LLM generation, finalization, orthopedist release and patient isolation over HTTPS. Restart the service and reboot the instance to verify persistence and interrupted-job recovery. Keep one API process active during updates. Stop it before consistent data backups; retain the old code and dependencies for rollback without overwriting runtime data.

The local test results do not establish Ubuntu installation, systemd boot, AWS sizing, provider connectivity, backup/restore or production readiness. Validate these on staging before public access.

## Local verification record (2026-09-29)

- Complete maintained backend suite: 78 passed, including real checkpoint inference on synthetic DICOM and restart/session-cookie regressions. One upstream Starlette/httpx deprecation warning remains.
- Browser suite: 38 passed in installed Microsoft Edge, desktop and mobile viewport projects. API responses in this suite are explicit fixtures.
- Frontend workflow suite: 6 passed. Production build and lint passed.
- Service structure and LF endings checked; systemd execution not tested because no running Linux engine is available on this workstation.

The old bytecode-only test bridge was replaced with maintained deployment regressions; the earlier suite count is therefore not directly comparable. Old JSON-first case tests were rewritten for the multipart contract actually used by the frontend, including demographics, DICOM identity, storage, audit integrity, role checks, malformed-upload cleanup and retry. The reference browser test now uses `/radiologist/cases/sample-case` and checks that private scan overlays are absent. No application authorization gate or report validation was relaxed.
