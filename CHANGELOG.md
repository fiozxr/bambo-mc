# Changelog

All notable changes to bambo-mc are documented here (project-initiated work, not upstream PNX).

## [2.2.0] — 2026-11-02 — End-user configuration

### Added
- **`bambo.conf`** — a single, human-friendly user configuration file (auto-created from
  the new `config.example`). Keys: server name/sub-name, max players, Xbox auth, allowlist,
  difficulty, gamemode, view distance, PvP, metrics, heap, backup retention, dashboard
  host/port/token.
- **`bambo config init | show | set | apply | wizard`**:
  - `init` — (re)create `bambo.conf` from `config.example` (mode 0600)
  - `show` — print effective settings (config + defaults)
  - `set <KEY> <value>` — edit one setting safely, preserving comments/order
  - `apply [--restart]` — validate ranges/booleans and deploy to `runtime/pnx.yml`
  - `wizard [--defaults] [--apply]` — interactive prompts (no config knowledge needed)
- `motd` now goes through the same config pipeline (update config + deploy + restart).
- `install.sh --auto` also creates `bambo.conf` if missing.

### Changed
- Tool/dashboard version bump to 2.2.0; README gained an end-user Configuration section.
- Legacy direct `config set` (pnx editing) removed; `config apply-template` remains for
  one-way template restore.

### Fixed
- Config changes now apply within the same invocation (set → apply) by refreshing the
  in-shell value.
- Variable-name collision between user-config keys and pnx keys (renamed to `PNX_CONFIG_KEYS`).

## [2.1.0] — 2026-11-02 — "Ready to go" automatic setup

### Added
- **`bambo bootstrap`** (alias of `./install.sh --auto`): one-command fresh-machine setup.
  Ensures system dependencies (java 21+, tmux, python3, curl, ip via apt/dnf/zypper/pacman),
  the verified+pinned server jar, the global wrappers, the nightly backup cron, and the
  dashboard token — then launches the dashboard, and optionally the game server with `--start`.
- **`install.sh --dry-run`** — true preview mode: prints the full plan, mutates nothing
  (verified: wrapper checksums, crontab and backups/ unchanged).
- **`install.sh --start`** — with `--auto`, also starts the game server after installing.
- `make bootstrap` convenience target.

### Changed
- Tool/dashboard version bump to 2.1.0.
- README quick start now leads with the bootstrap flow; RUNBOOK gained a "Fresh machine" section.

### Fixed
- `--dry-run` previously fell through into the normal install flow (installing wrappers /
  launching the dashboard); it now exits before any mutation.

## [2.0.0] — 2026-11-02 — Production-hardening release

Implements the "CEO pass": version control, diagnostics, reproducibility, and security hardening.

### Added
- **Version control**: repository initialized (git); `.gitignore` for secrets/runtime data.
- **`bambo doctor`** — self-diagnostics (system, java, tmux, network, config, cron, backup retention).
- **`bambo health [--json]`** — machine-readable health state for monitoring/tooling.
- **`bambo version`** — tool + server version, protocol, client target.
- **`bambo config get|set|diff|apply`** — comment-preserving YAML-safe config editing (stdlib python3);
  `config diff` compares live `runtime/pnx.yml` against the tracked `server/pnx.yml` template.
- **Reproducible setup** — `runtime/bambo.state.json` pins the installed PNX tag, sha256, protocol and
  client version; swapping jars keeps `powernukkitx.jar.prev` for offline rollback.
- **Locking** — `flock`-based guard for start/stop/backup/restore/setup to prevent races.
- **Backup manifests** — each snapshot records `manifest.json` (tool version, sources, sizes,
  sha256 of the LevelDB CURRENT); verification runs automatically after snapshot.
- **Watchdog** — `bambo watch` (opt-in) restarts a crashed server unless it was stopped
  intentionally (`runtime/.bambo.intentional-stop`); logs to `logs/watchdog.log`.
- **Dashboard hardening**: atomic token creation + `BAMBO_DASH_TOKEN` override, `bambo dash token-new`
  rotation, per-IP failed-auth rate limiting, audit log (`logs/dash-audit.log`), request log
  (`logs/dash.log`), security headers (CSP, nosniff, frame deny), request-size cap, graceful shutdown.
- **`empty-serve`**: build+test runner (`run-tests.sh`) for all layers; fixed a ping-log printf bug.
- **CI (GitHub Actions)**: CLI + dash checks, java layer tests. **Makefile** for local tasks.
- **Docs**: `README.md` rewritten; `docs/RUNBOOK.md`, `SECURITY.md`, `CONTRIBUTING.md`,
  `CHANGELOG.md`; systemd unit templates in `deploy/`.

### Changed
- `server/pnx.yml` template aligned with the live hardened baseline (`xboxAuth: false`,
  `enableMetrics: false`, MOTD default `bambo-mc`).
- `bambo` internals: shared `config` editor used by `motd`; status output stable; `logs` falls back
  to the log file when the server is stopped.
- `install.sh` gains `--check` (analyze only) and `--version`.

### Fixed
- README/crontab mismatch (backup log lives at `logs/cron-backup.log`).
- `empty-serve` README duplicate section headings; `PingServer` mis-printed `theirVer` as sender name.
- Dashboard: token file write made atomic; malformed/oversized POST bodies handled; `cmd` args reject newlines.

## [1.0.0] — 2026-10-17 — initial release (project states)

Home LAN Minecraft Bedrock server & tooling as originally assembled: `bambo` CLI, dashboard,
installer, backups, docs, and the `empty-serve` learning project. See git history / README.
