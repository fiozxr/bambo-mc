# Changelog

All notable changes to bambo-mc are documented here (project-initiated work, not upstream PNX).

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
