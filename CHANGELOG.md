# Changelog

All notable changes to bambo-mc are documented here (project-initiated work, not upstream PNX).

## [2.5.4] — 2026-11-02 — One-command curl installer + professional README

### Added
- `curl -fsSL https://raw.githubusercontent.com/fiozxr/bambo-mc/main/install.sh | bash` now works on a fresh machine: the installer self-downloads the project (git clone or tarball), then proceeds with the interactive version menu and global install.
- Professional README rewrite: install/quick-start/features/CLI/config/backups/security/layout/dev docs.

### Changed
- Version bump to 2.5.4.


## [2.5.3] — 2026-11-02 — Plain installer asks; menu version picker

### Changed
- `./install.sh` now asks for the server version whenever run in a terminal: a numbered menu (latest stable, match client, specific PNX releases, custom tag) before the download. Non-interactive runs keep using latest stable.
- `bambo setup --menu` exposes the same picker for manual installs/upgrades.
- Final installer message points to `bambo start`.
- Version bump to 2.5.3.


## [2.5.2] — 2026-11-02 — Ask by default; updates ask too

### Changed
- Interactive installs now ask by default: `install.sh --auto` / `bambo bootstrap` prompt for the server release matching the detected client version vs latest. Add `--no-ask` to skip and always take latest.
- `bambo update --ask` (alias `update ask`): ask before an upgrade whether to match the detected client version or go to latest stable.
- During interactive installs, the configuration wizard runs (`bambo config wizard --apply`) so server name/max players/etc. are asked up front.
- Tool/dashboard version bump to 2.5.2.


## [2.5.1] — 2026-11-02 — Client-version matching installer

### Added
- **`bambo setup --ask`** / **`bambo bootstrap --ask`** / **`install.sh --auto --ask`**:
  detects a locally installed Bedrock client version (Linux launcher caches, override with
  `BAMBO_CLIENT_VERSION`), maps it to the matching PNX release (1.26.60 → 3.0.6,
  1.26.50 → 3.0.5, …), and asks whether to install the matching server or the latest stable.
  Non-interactive runs keep using the latest stable.

### Changed
- Tool/dashboard version bump to 2.5.1.


## [2.5.0] — 2026-11-02 — Engine upgrade to PNX 3.0.6

### Changed
- **Server engine upgraded to PowerNukkitX 3.0.6** (2026-10-28): Minecraft 1.26.60,
  protocol 2225. Previous jar preserved as `powernukkitx.jar.prev` for offline rollback.
- `pnx_facts` and `docs/VERSIONS.md` updated for 3.0.6 (2225 / 1.26.60).
- Tool/dashboard version bump to 2.5.0.

### Action required (clients)
- Every client must now be on **Bedrock 1.26.60** (protocol 2225). If a device cannot
  update, roll the server back with `bambo setup 3.0.5`.

## [2.4.0] — 2026-11-02 — Invented the missing pieces

### Added
- **`bambo update check|apply`** — upstream awareness: compares the pinned PNX version
  against the latest GitHub release (`check`); `apply` performs the safe upgrade path
  (stop → backup → verified install → restart only if it was running).
- **`bambo world trash list|restore|purge`** — deleted worlds are recoverable:
  list trash, restore by world name or full id (unique-match), purge permanently.
- **`bambo user info <player>`** — operator / whitelist / banned dossier.
- **Webhook notifications** — optional `BAMBO_WEBHOOK_URL` (config) sends JSON alerts
  on server start/stop, backup completion, and watchdog crash-restarts.
- **`bambo maintenance status|on|off`** — scheduled daily auto-restart at 04:00
  (cron-managed, reversible, crontab backed up).
- **`bambo audit [n]`** — recent dashboard actions; **`bambo docs [README|runbook|security]`**
  — documentation from the shell.
- `health --json` now also reports `backups` count and `disk_free_kb`.

### Changed
- Tool/dashboard version bump to 2.4.0; README/usage/man updated.
- `user gamemode` now validates 0–3.

### Fixed
- World-trash restore parses the timestamped id correctly for names containing `-`.

## [2.3.0] — 2026-11-02 — Worlds + user management (dashboard-driven)

### Added
- **World management** (`bambo world …`, also in the dashboard):
  - `list` — worlds with size + default marker
  - `create <name> [--template <world>]` — copy an existing world into a new one
  - `rename <old> <new>` — also fixes the default-world pointer when needed
  - `delete <name> [--force]` — moves the world to `runtime/.trash/worlds` (reversible,
    never hard-deletes; the default world is protected unless another default is chosen)
  - `default <name>` — switch the world the server serves (restart applies)
  - All mutating operations require the server stopped, are name-validated
    (`[A-Za-z0-9_-]+`) and lock-protected.
- **User management** (`bambo user …`, also in the dashboard): `list`, `op`/`deop`,
  `whitelist`, `ban <player> [reason]`, `unban`, `kick <player> [reason]`,
  `gamemode <0-3> [player]`.
- **Server utilities** (`bambo plugins`, `bambo broadcast <msg>`, `bambo tps`) + dashboard buttons.
- Dashboard gained Worlds (create/rename/delete/default + save-all), Users (ban/unban/kick/
  gamemode/ops), and Utilities (plugins/tps/broadcast) cards.

### Changed
- Tool/dashboard version bump to 2.3.0; README command table expanded.

### Fixed
- `world list` exit status was 1 when worlds existed (trailing conditional) — now 0.

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
