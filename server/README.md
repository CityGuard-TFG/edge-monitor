# Server (FastAPI backend)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

Endpoints are under `/api/*` — see the repository root `README.md` for the
full API surface and deployment instructions.
