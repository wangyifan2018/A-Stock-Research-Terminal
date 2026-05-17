# Contributing to OpenFR

Thanks for helping improve OpenFR. This project combines a FastAPI backend,
LangGraph research orchestration, AKShare data tools, and a Next.js dashboard.

## Development Setup

1. Use Python 3.10+ and install the backend package in editable mode.
2. Install the web dependencies from `web/package.json`.
3. Keep local secrets in `.env.local` or another untracked environment file.

## Quality Checks

Before opening a pull request, run the focused checks for the area you changed:

```bash
.venv/bin/python -m pytest
cd web && npm run typecheck && npm run test && npm run build
```

## Safety Notes

- Do not commit API keys, `.env` files, local caches, or generated build output.
- AKShare and upstream market data providers can be slow or unstable; prefer
  bounded timeouts, caching, and graceful degradation over hard failures.
- `py_mini_racer` is disabled by default because some macOS/Python combinations
  can crash at the native layer. Only enable it in an isolated environment known
  to be stable.

## Pull Request Guidelines

- Keep changes focused and reviewable.
- Include tests for backend contracts, SSE parsing, and user-facing workflows
  when behavior changes.
- Mention any new environment variables and update documentation when needed.
