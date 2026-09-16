import json
from urllib import error, request
from os import environ

BACKEND_URL = environ.get("KNEE_AI_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


def handler(req, res):
    """Proxy /api/* to the FastAPI backend used by this app."""
    path = req.path or "/"
    if path == "/api":
        path = "/"
    elif path.startswith("/api"):
        path = path[len("/api") :] or "/"

    url = f"{BACKEND_URL}{path}"
    if getattr(req, "query", None):
        url = f"{url}?{req.query}"

    headers = {}
    for key, value in req.headers.items():
        lower = key.lower()
        if lower in {"host", "content-length"}:
            continue
        headers[key] = value

    data = None
    if hasattr(req, "body") and req.body:
        data = req.body
    elif hasattr(req, "get_data"):
        try:
            data = req.get_data()
        except Exception:
            data = None

    upstream_req = request.Request(url, data=data, method=req.method, headers=headers)

    try:
        with request.urlopen(upstream_req, timeout=60) as upstream:
            payload = upstream.read()
            res.status = upstream.status
            res.headers["Content-Type"] = upstream.headers.get("Content-Type", "application/json")
            res.headers["Access-Control-Allow-Origin"] = "*"
            res.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS,PATCH"
            res.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
            return payload
    except error.HTTPError as exc:
        payload = exc.read()
        res.status = exc.code
        res.headers["Content-Type"] = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
        res.headers["Access-Control-Allow-Origin"] = "*"
        res.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS,PATCH"
        res.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
        return payload
    except Exception as exc:
        res.status = 502
        res.headers["Content-Type"] = "application/json"
        res.headers["Access-Control-Allow-Origin"] = "*"
        res.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS,PATCH"
        res.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
        return json.dumps({
            "error": "KNEURA backend unavailable",
            "detail": str(exc),
        }).encode("utf-8")
