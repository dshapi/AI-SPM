# Contributing to Orbyx AI SPM

Thanks for your interest in contributing! Help wanted.. !

“Add new guard model integrations”
“Improve OPA policies for tool control”
“Add attack simulation scenarios”

---

## Getting Started

1. Fork the repository and clone your fork
2. Follow [README.md/Installation](./README.md/#installation) to get the platform running locally
3. Create a feature branch: `git checkout -b feat/your-feature-name`

---

## Development Workflow

### Making changes

Most services are hot-reloaded in development. After editing Python files, rebuild only the affected service:

```bash
docker compose up -d --build api          # API changes
docker compose up -d --build spm-api      # SPM API changes
docker compose up -d --build ui           # Frontend changes
```

### Running tests

```bash
make test              # unit tests (no Docker needed)
make smoke-test        # end-to-end test against running platform
```

Tests live in `tests/`. Please add or update tests for any new behaviour.

### Checking logs

```bash
make logs              # all services
make logs-api          # single service
```

---

## Pull Request Guidelines

- **One concern per PR** — keep changes focused and reviewable
- **Write a clear description** — what changed and why
- **Include tests** — new features and bug fixes should have test coverage
- **Pass CI** — all tests must be green before review
- **Update docs** — if you change behaviour, update the relevant `.md` file

Branch naming:

| Type | Pattern |
|---|---|
| Feature | `feat/short-description` |
| Bug fix | `fix/short-description` |
| Docs | `docs/short-description` |
| Refactor | `refactor/short-description` |

---

## Project Structure

```
services/          # Backend microservices (Python / FastAPI)
ui/                # Frontend (React + Vite)
platform_shared/   # Shared Python modules (JWT, Kafka, models)
spm/               # SPM policy and compliance definitions
opa/               # OPA Rego policies
grafana/           # Dashboard JSON and provisioning config
prometheus/        # Scrape config
tests/             # Unit and integration tests
scripts/           # Dev utilities (JWT minting, etc.)
```

---

## Reporting Issues

Please open a GitHub Issue and include:

- A clear description of the problem
- Steps to reproduce
- Relevant logs (`make logs-api` output)
- Your environment (OS, Docker version, chip architecture)

---

## Code Style

- **Python** — follow PEP 8; use type hints where practical
- **JavaScript** — standard ESM; no external linting config required
- **Commits** — use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, etc.)

---

*For a full feature reference see [FEATURES.md](./FEATURES.md).*
