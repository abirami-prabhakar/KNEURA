# KNEURA EC2 deployment readiness

Audited 2026-09-26. Verdict: **not ready to deploy as-is**. A restricted single-instance demo is feasible after the release and configuration blockers below are resolved. Public production use with real patient data requires additional operational and access-control work.

This audit examined the current Windows working tree, Git HEAD, runtime configuration, persistence, model and LLM integration, dependencies, and automated tests. No AWS resources were created or inspected. No production cases were approved or changed. Application code and dependencies were not upgraded during this audit. An isolated audit-tool environment and test artifacts were created under `.kneura/` and `test-results/`.

**Verification results**

| Check | Result | Meaning |
|---|---|---|
| Frontend production build | Passed | Current working tree builds; this does not validate Git HEAD or Linux installation. |
| Frontend lint | Passed | `npm run lint`, exit 0. |
| Complete backend suite | 94 passed, 10 failed | `python -B -m pytest tests -q`; not a green release gate. |
| Complete desktop/mobile browser suite | 36 passed, 2 failed | Both failures are the reference-handoff route test. |
| npm advisory scan | 0 reported | Scan of current lockfile, including development dependencies. |
| Python dependency consistency | Passed | `pip check`; consistency is separate from vulnerability scanning. |
| Python advisory scan | 29 entries, 16 distinct IDs, 3 packages | Installed backend dependency graph, 40 packages; duplicate feed entries included in the tool total. |
| Real-backend handoff | Passed earlier in this session | Actual DICOM/model, report, finalization, orthopedist release, refresh/re-login and patient isolation. |
| Live Gemini generation | Passed earlier in this session | Actual Gemini draft saved and reviewed through the browser using an isolated synthetic study. |
| Linux/EC2 installation and reboot | Not verified | Docker CLI exists but its Linux daemon is unavailable; no EC2 account/environment was exercised. |
| Load/concurrency testing | Not performed | Instance sizing below is a starting point, not measured capacity. |

**Release blockers**

1. **A fresh checkout of the current commit is broken.** Git HEAD contains conflict markers in 18 source/configuration files, including `backend/app.py`, `src/App.tsx`, `src/api.ts`, `src/types.ts`, and `vite.config.ts`. Fourteen committed Python files fail AST parsing. The working-tree Python files parse successfully, but those fixes are not all represented in HEAD. `run_kneura.ps1` is also untracked. Produce and test a clean release commit/artifact before deploying; copying whatever happens to be on this workstation is not reproducible.

2. **Local data remains tracked by Git.** The index lists 771 files under `.kneura/`, 54 SQLite files across the repository, 36 bytecode files, and 92 test-result files. These categories overlap. This includes the live database path, imaging/test artifacts and cached checkpoints. `.gitignore` does not remove already tracked files. Do not publish or deploy these data directories as application code. Preserve local data and backups while removing tracked runtime artifacts from the release. Review existing repository access/history before sharing it. No private `.env` file is currently tracked; a full historical secret scan was not performed.

3. **Known dependency advisories require remediation and retesting.** The audited installed versions and scanner-reported fixes are:

   | Package | Installed | Distinct advisory IDs | Scanner-reported fixed version |
   |---|---|---|---|
   | AnyIO | 4.13.0 | 2 | 4.14.2 |
   | IDNA | 3.11 | 1 | 3.15 |
   | Pillow | 12.2.0 | 13 | 12.3.0 |

   These are package-level findings, not proof that every vulnerable code path is reachable in KNEURA. Update compatible versions in an isolated environment, rerun imaging/report tests, and lock the tested dependency graph. The current `backend/requirements.txt` uses broad ranges, including independently ranged torch/torchvision versions. It does not reproduce the tested environment. The advisory scan describes this Windows environment; audit the eventual Linux artifact separately. Primary advisory examples: [AnyIO](https://github.com/agronholm/anyio/security/advisories/GHSA-82r6-8w77-94w6), [IDNA](https://github.com/kjd/idna/security/advisories/GHSA-65pc-fj4g-8rjx), [Pillow JPEG2000](https://github.com/python-pillow/Pillow/security/advisories/GHSA-vjc4-5qp5-m44j).

4. **Linux startup and process supervision are missing.** `package.json:14` starts PowerShell, and the only deployment file is `deploy/Caddyfile.example`. There is no checked-in systemd unit, Docker deployment, restart policy, or Linux bootstrap. The Python source itself uses portable paths; the active backend no longer imports the recovery bytecode loader. For Ubuntu EC2, install a tested Python/torch combination in a virtual environment and run Uvicorn as a dedicated non-root systemd service. Serve built `dist/` through Caddy; do not expose the Vite development server.

5. **Production origin, cookie and secret configuration must be explicit.** `backend/app.py:103` allows localhost origins by default; browser mutations from an HTTPS deployment domain will be rejected unless `KNEURA_ORIGINS` is set. Session cookies become Secure only with `KNEURA_SECURE_COOKIE=1` (`backend/app.py:197`). The backend does not automatically read dotenv files. The Windows launcher only imports its listed LLM variables, not every deployment variable in `.env.example`. Configure the Linux service environment, HTTPS/domain, writable data directory, checkpoint and LLM credentials deliberately. Keep provider credentials out of `VITE_*`, the frontend bundle, Git, and user-data logs. Prefer a narrowly scoped instance role to retrieve secrets. See [AWS Secrets Manager policies](https://docs.aws.amazon.com/secretsmanager/latest/userguide/auth-and-access_iam-policies.html).

6. **The full release test suite is not green.** Seven failures in `tests/test_patient_cases.py` exercise JSON-first patient creation and separate study attachment. The current app registers multipart study upload; the older `backend/patient_cases.py` installer is not installed. Three failures in `tests/test_recovered_backend.py` come from executing a stale Python 3.14 pytest `.pyc`, with old authorization and narrative expectations. Replace that compiled test bridge with maintained source tests and reconcile the obsolete API tests with the intended supported contract. Do not suppress failures without resolving that contract. The two browser failures expect `/radiologist/handoff` to show a heading that is no longer rendered there; the current sample is accessed through `/radiologist/cases/sample-case`.

**Runtime constraints and production gaps**

| Area | Current implementation | Required deployment treatment |
|---|---|---|
| Processes/jobs | In-process FastAPI background tasks and Python locks; startup marks active jobs interrupted (`backend/app.py:75`, `backend/report_jobs.py:18`) | Exactly one API worker and one active app instance. Multiple workers can race on whole-case writes and startup recovery. Introduce a durable queue and cross-process coordination before scaling out. |
| Storage | SQLite JSON records plus DICOM/PNG/NumPy files under `KNEURA_DATA_DIR` (`backend/app.py:30`) | Use a persistent encrypted EBS data volume outside the release directory. Configure retention/deletion settings and disk alarms. Do not use instance store for durable cases. |
| Backup/recovery | Verified offline archive helper already exists (`backend/recovery.py:13`); CLI requires server stopped | Schedule consistent database-plus-imaging backups, store encrypted copies off-instance, and prove restore on a clean host. Define retention and acceptable downtime/data loss. A helper is not an operating backup schedule. |
| Upload resources | 512 MiB/5,000-file checks; ZIP entries and DICOM data are held in memory | Add reverse-proxy request limits, concurrency limits and disk quotas; include multipart overhead in limits. Benchmark large/compressed studies before increasing access. App checks occur after multipart handling. |
| Model | CPU-only inference, maximum four torch threads, serialized model execution (`backend/inference.py:63`) | Package the full trusted checkpoint or complete `Model/` tree. Validate checksum and actual inference at deployment. A GPU instance will not accelerate the current hardcoded CPU path. Test required DICOM transfer-syntax decoders. |
| Readiness | `/api/health` reports API/worker status; model/LLM checks are separate | Add startup/readiness and external alerts that detect missing model, unavailable LLM, storage problems and stuck jobs. Monitor memory/disk as well as CPU. |
| Access control | Radiologists see the shared worklist; every orthopedist sees every FINAL case; patients require release and exact DICOM PatientID | This matches the requested single-team workflow. It is not multi-hospital/tenant isolation. Define team boundaries and account lifecycle before broader clinical access. |
| LLM | Approved finding allowlist, output validation, real provider attribution, no silent fallback | Validate provider connectivity from EC2, timeouts, quota and failure recovery. The optional free-text indication is not automatically de-identified; establish permitted data handling before using real patient context. |
| Public assets | `src/handoff.tsx` eagerly bundles supplied golden-case metadata and Grad-CAM images | Confirm these reference assets are approved for public distribution or omit them from the production build. UI login does not protect files included in public JavaScript/static assets. |
| Operations | No checked-in monitoring, deployment pipeline, rollback or automated dependency-update gate | Add service restart on boot, release/version records, log rotation/retention, backup alerts, a rollback procedure and a clean Linux smoke test. |

EBS volume retention depends on its deletion setting; instance-store data does not survive stop/termination. See [AWS storage persistence](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Storage.html) and [EBS termination settings](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/preserving-volumes-on-termination.html). Memory/disk monitoring can be added with the [CloudWatch agent](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/metrics-collected-by-CloudWatch-agent.html). Caddy supports an explicit [request-body limit](https://caddyserver.com/docs/caddyfile/directives/request_body).

**Suggested first EC2 layout, after blockers are cleared**

Use one x86-64 Linux instance, a tested supported Python version with compatible CPU torch/torchvision wheels, and one Uvicorn worker bound to `127.0.0.1:8000`. Put Caddy on HTTPS port 443, serving `dist/` and proxying `/api/*`. An initial capacity-test candidate is 4 vCPU/16 GiB RAM, for example `m7i.xlarge`; this is a provisional engineering estimate, not an established minimum. See [AWS instance specifications](https://docs.aws.amazon.com/ec2/latest/instancetypes/gp.html). Benchmark representative studies and concurrent use before selecting the final size or storage capacity.

Use encrypted persistent data storage, restricted administrative access through SSM or trusted IPs, IMDSv2, least-privilege IAM, and no public ingress to ports 8000 or 5173. Permit only the required web ports and outbound services. See [AWS EC2 infrastructure security](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/infrastructure-security.html) and [IMDSv2 guidance](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-metadata-transition-to-version-2.html?trk=article-ssr-frontend-pulse_little-text-block).

The eventual service needs at least these non-secret settings; values below are illustrative, not an applied configuration:

```text
KNEURA_DATA_DIR=/var/lib/kneura
KNEURA_ORIGINS=https://your-domain.example
KNEURA_SECURE_COOKIE=1
KNEURA_CHECKPOINT=/opt/kneura/model/verified-checkpoint.pt
VITE_API_BASE_URL=/api
```

Also provide the existing LLM URL, model, provider, key, timeout and retry settings securely. `VITE_API_BASE_URL` is a build-time frontend setting; backend secrets are runtime service settings. Configure Caddy's `KNEURA_HOST` and `KNEURA_DIST`. Do not introduce a second API process during rolling updates with this architecture.

**Go/no-go sequence**

1. Create a clean release containing the working source, excluding databases, imaging, secrets, caches and test artifacts; address already tracked data without deleting the user's local cases.
2. Update and lock the compatible Python dependency graph, then resolve the obsolete test contracts and get the supported complete test suite green.
3. Add and validate the Linux service/proxy configuration with one worker, HTTPS, correct origins, secure cookies, persistent storage and secret loading.
4. Boot a clean EC2 staging instance and run the actual workflow: upload demographics and DICOM, real inference/evidence, real Gemini report, finalization, orthopedist release and patient isolation.
5. Verify reboot persistence, interrupted-job behavior, oversized upload handling, provider outage, backup/restore and disk/resource alarms. Repeat from the clean release artifact rather than this workstation.
6. For a public clinical deployment, complete organization-specific access, privacy, provider-data and operational reviews. Software demo tests do not establish clinical validation.

Only audit documentation was added to source during this request. Remaining blockers are reported, not silently fixed or waived.
