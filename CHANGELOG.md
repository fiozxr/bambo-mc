# Changelog

All notable changes to bambo-mc are documented here (project-initiated work, not upstream PNX).

## [2.6.0] — 2026-11-04 — Dashboard rebuilt as an operations console

The web dashboard was a wall of rounded glass cards with gradient washes and ALL-CAPS
labels - a generic look that also hid the two things an operator actually checks. It is
rebuilt as a dense NOC-style console, following current dashboard practice for
monitoring UIs (status clarity first, colour reserved for genuine anomalies, tabular
figures so live values cannot jitter, progressive disclosure instead of one flat page).

### Added — what the page now answers
- **Status strip above the fold**: running / up-but-unreachable / stopped as a word plus a
  dot (never colour alone), uptime, players online vs max, last activity, engine build.
- **Join card**: the address on its own with a Copy button, the port, whether it is
  listening, and whether the dashboard is bound to localhost or the network.
- **Heartbeat**: an inline-SVG sparkline of players online over the last few minutes, with
  the spans where the server was down shaded. No chart library, no canvas, no deps.
- **Alerts**: derived, not decorative - up but nothing listening, backups older than 36h,
  no snapshots, errors in the log window, engine version unrecorded, and open
  authentication combined with an exposed dashboard bind.
- **Log viewer**: entries parsed into time/level/message, level chips (info/warn/error/
  debug), text filter, Follow toggle that stops the view jumping and reports how many
  lines arrived while paused.
- **Tables where there were text blobs**: worlds (size, default, Make default), backups
  (age, newest first, Restore), operators/allow list, players.
- **Left rail navigation** that tracks the section in view, and a live/offline indicator
  so a dead dashboard says so instead of freezing on stale values.
- Light and dark themes: follows `prefers-color-scheme`, with a remembered toggle.
- Destructive controls (Stop, Restart, Back up, Save name, world delete, restore,
  engine rollback) arm on the first press and act on the second, with the consequence in
  the confirmation line; an in-flight command says so rather than silently no-oping.
- Polling pauses while the tab is hidden and backs off when the dashboard stops
  answering, which matters on a phone hotspot.

### Added — API
- `GET /api/log?limit=N` returns structured entries (`ts`, `level`, `tag`, `msg`), so the
  log has its own cadence instead of riding the status poll.
- `/api/status` gained `config` (from `runtime/pnx.yml`), `version` (from
  `runtime/bambo.state.json`), `health` (boot time, uptime, players online, last activity,
  error/warning counts), `alerts`, `history`, `port`, `join_ip` and `exposed` - all derived
  from file reads, with no extra subprocess per poll. `players` is now a real count, or
  `null` when the log window cannot prove it, rather than always `null`.
- Actions the console can now reach: `restore`, `rollback`, `update`, `maintenance`.
  Destructive log parsing is honest: a player count is only shown when the boot marker is
  inside the window that was read.

### Fixed during the rebuild (found by driving the real page in a headless DOM)
- `stop`/`restart`/`backup`/world delete/name save fired on a single click: the arm flag
  was set by a listener on the button and checked by a delegated document listener in the
  same click, so the guard could never work. Confirmation moved into the document
  listener, which always runs after the button's own.
- A string was passed where a DOM node was expected (`op list` result panel), which threw
  on click.
- Two different `world` actions shared a busy-lock keyed on the action name, so a queued
  `world create` silently swallowed `world delete`; the lock is per control now and
  reports when something is already running.
- The engine-rollback control bypassed its own confirmation entirely.
- A nested ternary in the version card did not parse - the whole page script failed to
  load, which a syntax check now catches before it ships.

### Tests
- `dash_smoke` grew a page contract check: every `#id` the script reaches for must exist in
  the markup, `innerHTML` may only ever be assigned an empty string (the SECURITY.md
  promise that server text never becomes markup), every `*Btn` must have a handler, plus
  assertions for the new status fields and the `/api/log` entry shape. 28 checks.
- Version is read from `BAMBO_VERSION` rather than hard-coded, so this bump needed no test
  edits.

Not verified: visual rendering in a real browser. No Chromium is available on the
development machine, so the page was driven through a headless DOM instead - it proves
behaviour and wiring, not pixels.


## [2.5.6] — 2026-11-03 — Bug-fix pass: dashboard, console output, rollback

### Fixed — dashboard (`bin/bambo-dash.py`)
- The log tail was unreadable: `log_tail()` "stripped" colour codes by deleting the
  characters `§eabrc6`, which also ate every `e`, `a`, `b`, `r`, `c` and `6` in the log
  (`Loading is complete for level` rendered as `Loding is omplt fo lvl`, `1.26.0` as
  `1.2.0`). A colour code is now removed as `§` plus its one code character, along with
  ANSI sequences.
- Players / TPS / Plugins displayed the *previous* command's output (see the
  `console_out` fix below) — the dashboard was faithfully relaying stale text.
- `/api/status` took ~2.1s while the page polls it every 3s, so the State card was
  almost always stale. It shelled out three times and re-read the whole log per poll;
  `join`, `backups` and `others` are now memoized (37-44ms warm).
- A machine without `tmux` got a permanent 500 on `/api/status`: `running()` let
  `FileNotFoundError` escape. It now reports "stopped".
- Auth: a token containing a non-ASCII character raised `TypeError` in
  `hmac.compare_digest` and returned HTTP 500 — a path that never reached the
  brute-force rate limiter. Both sides are compared as bytes, so it is a clean 401.
- HTTP keep-alive desync: the 413, 404-with-body and chunked paths left the request
  body unread in the socket, so the next request on that reused connection was parsed
  as garbage. The connection is now closed instead.
- Long actions (backup, restart, motd) could be killed at the 120s subprocess timeout
  mid-transfer; they now get 600s and report a timeout honestly.
- UI: the `refresh` button had no handler, and both `user|list` buttons threw a JS
  `TypeError` (missing entry in the selector map).

### Fixed — CLI (`bambo`)
- `console_out()` slept a fixed 0.8s and then dumped the tail of the pane, so on a busy
  server `tps`, `players`, `plugins` and `whitelist list` returned the PREVIOUS
  command's scrollback instead of their answer. It now waits for the console's own
  reply and prints only what followed the echoed command.
- `bambo tps` sent `/tps`, which PowerNukkitX rejects (`Unknown command: tps`). The real
  command is `status`, which reports `Current TPS`.
- `bambo rollback` was unreachable: the functions existed but no dispatcher case, help
  entry or manual entry did, so every form failed with "unknown option".
- `bambo rollback --prev` blanked the deployment state (writing `"tag": ""`), breaking
  `version`, `join` and `doctor`. `setup` now records the outgoing jar's `prev_*` facts,
  and `--prev` swaps jars *and* facts both ways — repeatable, and it refuses a legacy
  jar with no recorded version instead of corrupting state.
- All of `rollback_do`'s failure recovery was dead code, because `die()` exits the
  process: a failed backup left the server stopped with no restart. Its callees now run
  in subshells so the branches execute.
- The manual told users to run `bambo --host 0.0.0.0`, which is not a command. Corrected
  to the documented env-var mechanism.

### Fixed — installer (`install.sh`)
- `--no-ask` was documented but unhandled: it fell through to "unknown option" and
  exited 2, so non-interactive installs could not disable prompting.
- `--dry-run` was not pure — it created `bambo.conf` while printing "nothing was
  installed or modified".
- Install logs moved from predictable `/tmp/bambo-install-*.log` paths into the app's
  `logs/` (a fixed /tmp file written by a root-run installer is a symlink trap).
- `--uninstall` deleted any wrapper named `bambo*` in the bin dir when it could not
  identify the install, and matched the app path as a regex rather than a fixed string.
  It now refuses to remove wrappers it cannot attribute.
- `--help` showed a truncated option list (the header's last three lines were cut) and
  printed nothing at all when piped through `curl | bash`, where `$0` is the shell.

### Tests
- **`tests/cli_basics.sh` never called `summary()`** — it always exited 0, so every CLI
  assertion failure was silently ignored and CI could not go red. It now reports its
  tally and gates. (55 checks.)
- `dash_smoke`: replaced the racy fixed `sleep 1.5` with a readiness poll, and added a
  regression test for the log-tail mangling.
- Added rollback coverage: dispatch, unknown-version rejection, the two-way jar+state
  swap (skipped when a real server session is live), and refusal on an unrecorded jar.
- Version assertions now derive from `BAMBO_VERSION` instead of hard-coding it, and the
  dashboard's version is checked against the CLI's so they cannot drift apart.


## [2.5.5] — 2026-11-02 — Fully turnkey installer

### Changed
- The installer (plain `./install.sh` or `curl ... | bash`) now runs the COMPLETE setup by default: dependencies, interactive version choice, configuration wizard, nightly backup cron, token, global wrappers, dashboard. No `--auto` needed.
- After install, the only remaining step is `bambo start`.
- `--auto` remains accepted for compatibility; `--no-ask` disables prompts; `--dry-run` previews safely.
- Version bump to 2.5.5.


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
