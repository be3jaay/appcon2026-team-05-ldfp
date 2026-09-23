# sisa_app

Monorepo with a FastAPI backend (`sisa_api/`) and a Next.js frontend (`sisa_fe/`).

## Run with Docker Compose (recommended)

```bash
docker compose up --build
```

- API: http://localhost:8000 (health check at `/health`)
- Web: http://localhost:3000

Stop everything with:

```bash
docker compose down
```

## Run locally without Docker

### API

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
cd sisa_api
uv sync
uv run fastapi dev src/main.py
```

Runs at http://localhost:8000. Interactive docs at `/docs`, health check at `/health`.

### Web

Requires Node 22 and pnpm.

```bash
cd sisa_fe
pnpm install
pnpm dev
```

Runs at http://localhost:3000.

## Project structure

```
sisa_api/    FastAPI backend
sisa_fe/     Next.js frontend
docker-compose.yml   runs both services together
```
