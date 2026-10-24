# Run KNEURA with Docker

Use Docker Desktop with Linux containers (or Docker Engine with Compose on Linux). Run commands from the repository root.

```powershell
docker compose up -d --build --wait
docker compose exec api python -m backend.manage check-model
docker compose exec api python -m backend.manage create-user --email radiologist@kneura.local --name "Demo Radiologist" --role radiologist
```

The account command prompts for a password of at least 12 characters. Open **http://localhost:8080/login**. The first build downloads Node, Python and CPU PyTorch dependencies and can take several minutes. The supplied model is included; no GPU is required.

The web container serves the production React build and forwards `/api/` to a single API worker. The API port is internal. Health checks verify HTTP availability; `check-model` separately verifies actual model loading and inference. Compose waits for the API health check before starting the web service ([Docker startup order](https://docs.docker.com/compose/how-tos/startup-order/)).

## Data and accounts

The `kneura-data` named volume holds SQLite, uploaded images and generated evidence. This starts with a fresh database: local `.kneura/` data and accounts are not imported. They remain on your computer. Secrets, databases, caches and local MRI uploads are excluded from the image build context. The existing bundled handoff reference assets remain part of the frontend.

```powershell
docker compose ps
docker compose logs --tail 100 api web
docker compose down
docker compose up -d --wait
```

Stopping or rebuilding preserves the volume. **Do not use `docker compose down -v` unless you intend to delete Docker's stored accounts and cases.** Keep one API container/worker because jobs and locks are process-local.

## Optional LLM configuration

Without LLM settings, the explicit template report workflow is available; genuine narrative generation requires a configured provider. The API automatically loads `.env.kneura.local` when it exists. Set `KNEURA_LLM_URL`, `KNEURA_LLM_MODEL` and `KNEURA_LLM_KEY` (or `KNEURA_LLM_API_KEY`) in that ignored file, then apply changes:

```powershell
docker compose up -d --wait
```

The backend env file is loaded only into the API container at runtime; it is excluded from image builds. It also supports `LLM_PROVIDER`, `LLM_TIMEOUT_SECONDS` and `LLM_MAX_RETRIES`. Explicit settings in the Compose `environment` section override that file, including Docker's data directory and browser origins. Keep credentials in ignored local files. Never put them in `VITE_*` variables. A service running on your Windows host is reachable from Docker Desktop at `host.docker.internal`, not `localhost`.

## Change port or deploy to a server

Defaults bind to this computer only. Set these in an ignored `.env` file to change the local port:

```dotenv
KNEURA_PORT=8090
KNEURA_ORIGINS=http://localhost:8090,http://127.0.0.1:8090
```

For a remote server, place an HTTPS reverse proxy in front of the web port, set `KNEURA_ORIGINS=https://your-domain.example` and `KNEURA_SECURE_COOKIE=1`, then recreate the containers. The browser origin must match exactly or mutations are rejected. `KNEURA_BIND_ADDRESS` controls the published bind address; retain `127.0.0.1` for a proxy running on the host. The existing [deployment readiness audit](EC2_DEPLOYMENT_READINESS.md) describes additional limits for public deployment; containerization alone does not resolve them.

When requiring an eligibility CSV, set `KNEURA_REQUIRE_SERIES_CSV=1` and include it with each upload. Host filesystem paths are not automatically accessible inside containers.
