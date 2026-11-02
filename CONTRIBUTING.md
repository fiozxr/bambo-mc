# Contributing

Thanks for helping make bambo-mc better. The project is small and intentionally boring: it must
keep working for a family on a phone hotspot, with zero internet dependencies at play time.

## Ground rules

- **Keep it stdlib-only.** `bin/bambo-dash.py` has zero third-party dependencies; `bambo` is pure
  bash (+ tmux/curl/ip/jq-less); `empty-serve` is pure JDK. Adding a dependency is a design decision
  — discuss it first.
- **Keep it offline-friendly.** No external service may be required at runtime.
- **Keep the CLI contract.** `bambo stop && bambo backup && bambo start` (the cron line), `--dash`,
  and `--setup` are used by `install.sh` and cron — do not break them.
- **Test before you open a PR.** `make lint && make test && make java-test` must pass.
- **No secrets.** Never commit `dash.token` or anything under `runtime/` (git-ignored).

## Development loop

```sh
make lint        # bash -n, py_compile, shellcheck (if installed)
make test        # non-live test suite
make java-test   # build empty-serve + run layer self-tests & probes
make live        # full cycle on the real server (starts/stops it)
```

## Structure

| Path | What |
|---|---|
| `bambo` | the CLI (all control of server/dashboard/backups/config) |
| `bin/bambo-dash.py` | admin dashboard (token-gated, stdlib-only) |
| `bin/bambo-nettest` | LAN reachability probe |
| `install.sh` | installs global wrappers |
| `empty-serve/` | the from-scratch Bedrock server (MIT, pure JDK) |
| `server/pnx.yml` | tracked config template (baseline for `bambo config diff`) |
| `runtime/` | **machine-specific, git-ignored** — the live server data |
| `docs/`, `deploy/`, `tests/`, `.github/` | docs, systemd templates, tests, CI |

## Style

- Bash: `set -uo pipefail`, `local` everywhere, functions documented, no `eval`.
- Python: stdlib only, function-per-concern, no new runtime deps.
- Java: pure JDK, Javadoc on classes, self-test `main()` per layer.

## Versioning

See `CHANGELOG.md`. Bump the `BAMBO_VERSION` in `bambo` when behavior changes.
