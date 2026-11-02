# bambo-mc

A production-hardened, self-hosted **Minecraft Bedrock server** (PowerNukkitX) plus
admin tooling for a small group (up to 4 players) on one WiFi / phone hotspot.
**No port forwarding, no internet account required for players to join.**

```
bambo-mc ── v2.0.0 (production hardening)
├── bambo            the control CLI (services, dash, players/op/whitelist/world/cmd,
│                    config, backup/restore/setup, doctor/health, help/man)
├── bin/             dashboard (token-gated, stdlib-only) + LAN probe
├── install.sh       system-wide wrapper installer (user or system, or --check)
├── server/pnx.yml   tracked config template (baseline for `bambo config diff`)
├── runtime/         [git-ignored] live server: jar, worlds, players, backups, state
├── empty-serve/     our from-scratch Bedrock server (MIT, learning project)
├── forks/           [git-ignored] downloaded PowerNukkitX source (reference only)
├── docs/            architecture, version alignment, runbook
├── deploy/          optional systemd unit templates
├── tests/           test suite (make test / make live)
└── .github/         CI (CLI checks + Java layer tests)
```

> **Two engines, two licenses.** The *running* server is **PowerNukkitX 3.0.5**
> (LGPL-3.0) in `runtime/`. `empty-serve/` is a **separate, original, MIT-licensed**
> Bedrock server we are writing from scratch — it is **not playable yet** (see its
> own README). `NOTICE` records provenance; never conflate the two.

## What changed in v2 (production pass)

| Area | What was done |
|---|---|
| Version control | repository initialized; `.gitignore` protects secrets/runtime data |
| Reproducibility | `bambo setup` pins the deployment in `runtime/bambo.state.json` (tag, sha256, protocol, client); keeps the previous jar as `powernukkitx.jar.prev` |
| Diagnostics | `bambo doctor` (self-check) and `bambo health --json` (monitoring) |
| Config control | `bambo config get/set/diff/apply` — comment-preserving YAML-safe edits; template vs live drift view |
| Concurrency | flock-based locking on start/stop/backup/restore/setup |
| Backups | each snapshot now carries `manifest.json` and is integrity-checked automatically; restore list shows size/manifest |
| Availability | optional `bambo watch` watchdog (restarts crashed server unless intentionally stopped) |
| Dashboard | atomic token file + `BAMBO_DASH_TOKEN` override, `bambo dash token-new` rotation, per-IP brute-force rate limiting, audit log (`logs/dash-audit.log`), request log, security headers, request cap, graceful shutdown |
| Tests/CI | `tests/` suite (17 CLI checks, 15 dashboard API checks), empty-serve layer tests, GitHub Actions workflow |
| Docs | `docs/RUNBOOK.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, systemd templates |
| Fixes | ping-log printf bug in empty-serve; README/crontab log path mismatch; duplicate headings; dashboard token write race |

Full detail: `CHANGELOG.md`.

## Quick start

```sh
./install.sh              # analyse, install commands into ~/.local/bin, launch dashboard
bambo doctor              # everything OK? (non-zero exit if issues)
bambo up                  # start server + dashboard
bambo join                # the address to type into a client (changes with network!)
bambo status
bambo down
```

If the jar is missing: `bambo setup` (downloads + sha256-verifies the newest stable PNX).

## Core usage

| Command | What it does |
|---|---|
| `bambo up / down` | start/stop **all** services (server + dashboard) |
| `bambo start / stop / restart` | game server only (stop waits for world saves; force-kills only after 40s grace in cron) |
| `bambo status` | server + dashboard status, pinned PNX version |
| `bambo health [--json]` | health summary / machine-readable JSON |
| `bambo doctor` | self-diagnostics (tools, Java 21+, network, config, cron, perms) |
| `bambo dash start\|stop\|status\|logs\|token-new` | admin dashboard |
| `bambo logs [n]` / `bambo tail` | server console history / live attach |
| `bambo join` | current join address for clients |
| `bambo players`, `bambo op …`, `bambo whitelist …`, `bambo world …`, `bambo cmd …` | in-game admin |
| `bambo motd "<name>" ["<sub>"]` | set server-list name (edits config, restarts) |
| `bambo config get\|set\|diff\|apply` | inspect/edit `pnx.yml` safely |
| `bambo backup [--force]` | timestamped snapshot (worlds+players+config+manifest); newest 10 kept |
| `bambo restore list\|<ts>` | list or roll back to a snapshot (reversible) |
| `bambo setup [version]` | download/verify/pin the server jar (rollback: `bambo setup 3.0.5`) |
| `bambo watch [--once] [--interval=N]` | optional watchdog |

## Nightly backups

Installed by default (03:30):

```
30 3 * * * cd /home/fiozxr/bambo-mc && ./bambo stop && ./bambo backup && ./bambo start >> /home/fiozxr/bambo-mc/logs/cron-backup.log 2>&1
```

Check `logs/cron-backup.log` after a night; `doctor` reports if the cron line is missing.
Backups land in `runtime/backups/<timestamp>/`; the newest `BAMBO_KEEP` (default 10) are kept.
See `docs/RUNBOOK.md` for the restore drill.

## Security

- The dashboard binds **127.0.0.1** by default and is token-gated (`dash.token`,
  mode 0600, auto-generated, rotation via `bambo dash token-new`). Exposing it on the
  LAN (`BAMBO_DASH_HOST=0.0.0.0`) lets anyone holding the token control the server —
  do only on a trusted network.
- `xboxAuth: false` (offline mode) for the family LAN — player identity is self-reported;
  **do not expose this server to the public internet**.
- Rate-limited auth, audit log, request cap, security headers, no secrets in git.
- See `SECURITY.md`.

## Version alignment

Bedrock clients and servers must share a **protocol number**. Current deployment:
PNX **3.0.5** ↔ Bedrock **1.26.50** ↔ protocol **2193**. When a client auto-updates
past the server, see `docs/VERSIONS.md` for the cheapest fix.

## Layout notes

- `runtime/` is the engine's working directory (PNX resolves data paths from cwd) —
  `bambo` always launches from inside it.
- `server/pnx.yml` is the tracked template; `runtime/pnx.yml` is live. They are allowed
  to differ (live is customized); `bambo config diff` shows you exactly how.
- `logs/` holds cron, dashboard, audit and watchdog logs (server logs live in
  `runtime/logs/`).
- `forks/empty-serve` is the downloaded PNX source clone (own git repo, LGPL) — kept
  only as a reference; it is excluded from this repo's git.

## Development

```sh
make lint           # bash -n + py_compile + shellcheck (if installed)
make test           # non-live suite (CLI + dashboard API + empty-serve layers)
make smoke          # dashboard only
make live           # full cycle on the real server (starts/stops it)
make java-test      # empty-serve layers only
```

CI runs the same checks on every push (`.github/workflows/ci.yml`).

## Going further

- **systemd**: templates in `deploy/` (do not mix with tmux mode; see headers).
- **Monitoring**: `bambo health --json | grep '"up":true'` from cron, or a 5-minute
  timer; see `docs/RUNBOOK.md`.
- **Docs**: `docs/ARCHITECTURE.md`, `docs/VERSIONS.md`, `docs/RUNBOOK.md`.
