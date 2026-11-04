# bambo-mc

> Cross-platform Minecraft Bedrock server from one mobile hotspot / WiFi, with a GUI.  
> No Xbox account required, no port forwarding.

**bambo-mc** is a production-hardened, self-hosted **Minecraft Bedrock server** + admin
platform for a small group (up to ~20 players) on one WiFi / phone hotspot. It bundles the
server engine (PowerNukkitX), a full control CLI, a token-gated web dashboard, automatic
backups, an update system, and a one-command installer.

---

## Install (one command)

```sh
curl -fsSL https://raw.githubusercontent.com/fiozxr/bambo-mc/main/install.sh | bash
```

That downloads the project, installs everything globally (commands, server jar, dashboard
token, nightly backup cron), and — when run in a terminal — **asks which server version**
you want (matching your client, latest stable, or a specific release) and the configuration answers (press Enter to accept defaults). Everything is installed globally — all that remains is:

```sh
bambo start
```

Alternatives:

```sh
# clone + install manually
git clone https://github.com/fiozxr/bambo-mc.git && cd bambo-mc && ./install.sh

# system-wide (root) install
sudo ./install.sh --system

# preview what the automatic installer would do
curl -fsSL https://raw.githubusercontent.com/fiozxr/bambo-mc/main/install.sh | bash -s -- --auto --dry-run
```

Requirements: Linux, `bash`, `curl`, `tar` (installer fetches the rest: Java 21+, tmux,
python3, iproute2 — via apt/dnf/zypper/pacman).

---

## Quick start

```sh
bambo bootstrap --start   # full automatic setup (deps + server + cron + token + start)
bambo doctor              # self-diagnostics
bambo join                # the address players type into the client (changes with network!)
bambo status
```

After install, `bambo` (and `bambo-mc`, `bambo-dash`, `bambo-nettest`) are global.

---

## Features

| Area | Highlights |
|---|---|
| Server engine | PowerNukkitX (Bedrock). Pinned, sha256-verified releases; previous jar kept for rollback |
| Worlds | list / create / rename / delete / set-default / trash (undo). Offline-safe, reversible |
| Players | ban / unban / kick / gamemode / operators / whitelist / player info / online list |
| Console | full interactive console, broadcast, plugins list, TPS |
| Config | one friendly file `bambo.conf` + interactive wizard + validated apply |
| Backups | nightly automatic snapshots (worlds+players+config+manifest), retention, restore |
| Updates | `bambo update check/apply [--ask]` — upstream-aware, safe upgrade path |
| Dashboard | ops console at http://127.0.0.1:8787 - live status, alerts, heartbeat of who is in, filterable server log, players/worlds/backups, confirm-gated destructive actions (token-gated, audited, rate-limited) |
| Monitoring | `bambo health --json`, doctor, optional watchdog auto-restart, webhook alerts |
| Install | one-command bootstrap with interactive version & config prompts |
| Ops | scheduled daily restart, audit log, systemd templates, CI, tests |

---

## CLI reference (common)

```text
bambo up | down | status | restart      # services
bambo start | stop | logs | tail        # game server / console
bambo join                              # current join IP:port
bambo doctor | health [--json]          # diagnostics / monitoring
bambo setup [version] | setup --menu     # install server version (menu picker)
bambo update check | apply [--ask]      # upstream-aware upgrades
bambo config init | show | set | apply | wizard
bambo world list|create|rename|delete|default|trash|save|tp
bambo user list|info|op|deop|whitelist|ban|unban|kick|gamemode
bambo cmd "<console command>" | broadcast "<msg>" | plugins | tps
bambo backup | restore list|<ts>
bambo maintenance status|on|off          # daily auto-restart (04:00)
bambo audit [n] | docs [README|runbook|security]
```

Run `bambo man` for the full manual.

---

## Configuration

All user settings live in one file: **`bambo.conf`** (auto-created from `config.example`;
`KEY=value`, comments welcome). Edit it, or use the wizard:

```sh
bambo config wizard --apply    # interactive questions
bambo config set BAMBO_MAX_PLAYERS 10
bambo config apply [--restart]
```

Key settings: server name/subtitle, max players, Xbox auth, allowlist, difficulty, gamemode,
view distance, PvP, metrics, heap, backup retention, dashboard host/port, webhook URL.

---

## Backups

Nightly at 03:30: `bambo stop && bambo backup && bambo start` (cron-managed). Snapshots
to `runtime/backups/<ts>/` with a manifest + integrity check; newest 10 kept
(`BAMBO_KEEP`). Restore: `bambo restore list` → `bambo restore <ts>`.

---

## Security

- Dashboard binds 127.0.0.1 by default; token (`dash.token`, mode 0600), rotation via
  `bambo dash token-new`, per-IP rate limiting, audit log, security headers.
- Offline mode (`xboxAuth: false`) is for trusted LANs — do not expose to the public internet.
- No secrets in git (`dash.token`, `bambo.conf`, runtime data are ignored).
- See `SECURITY.md`.

---

## Project layout

```text
bambo            control CLI (everything)
install.sh        installer / one-command bootstrap
bin/             dashboard (stdlib-only) + LAN probe
config.example    template for bambo.conf
server/pnx.yml    tracked engine config template
runtime/          [machine-local] live server data (jar, worlds, players, backups, state)
empty-serve/      our from-scratch Bedrock server (MIT — learning project, not playable yet)
forks/           [reference only] downloaded PowerNukkitX source
logs/            cron / dashboard / audit / watchdog logs
docs/            architecture, version alignment, runbook
deploy/          systemd unit templates
tests/ + .github/  test suite + CI
```

Licensing: engine runtime is PowerNukkitX (LGPL-3.0); this project's own code is MIT.
See `NOTICE`.

---

## Development

```sh
make lint        # bash -n + py_compile + shellcheck
make test        # CLI + dashboard API + empty-serve layer tests
make live        # full cycle on a real server (starts/stops it)
```

CI runs the same checks on every push. See `CONTRIBUTING.md`.

---

## Docs & support

- Runbook: `docs/RUNBOOK.md` (or `bambo docs runbook`)
- Version alignment: `docs/VERSIONS.md`
- Security: `SECURITY.md` · Changelog: `CHANGELOG.md`
- Issues/feedback: https://github.com/fiozxr/bambo-mc/issues
