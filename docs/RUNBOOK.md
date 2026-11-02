# Runbook — day-to-day operations

Quick reference for the person who actually runs this thing. Full background: `README.md` and
`docs/ARCHITECTURE.md`.

## Fresh machine (automatic setup)

```sh
# from the repo, as your normal user (needs sudo for package installs):
./install.sh --auto --start      # or: bambo bootstrap --start
./install.sh --auto --dry-run    # preview what it would do
```

This ensures dependencies, the server jar (verified+pinned), the global commands, the
nightly backup cron, and the dashboard token — then (with `--start`) starts everything.
See `README.md` → "What `bambo bootstrap` does".

## Normal day

```sh
bambo status       # both services up?
bambo join         # what to type into a client (address changes with the network!)
```

Most "I want to change something" tasks start at the config file: `bambo config show`,
`bambo config wizard`, or `bambo config set <KEY> <value>` then `bambo config apply`
(see `README.md` → Configuration).

The join address changes whenever the laptop's lease changes — always take it from `bambo join`.

## Starting / stopping

```sh
bambo up           # server + dashboard
bambo down         # both, gracefully (worlds saved)
bambo start / stop # game server only (stop waits up to 40s for world saves)
```

Never `kill -9` the game server; it owns a LevelDB store. `bambo stop` sends the proper `stop`
console command and waits.

## Backups (automatic, nightly at 03:30 via crontab)

```sh
crontab -l         # shows: 30 3 * * * cd … && ./bambo stop && ./bambo backup && ./bambo start
tail -40 logs/cron-backup.log   # check it actually ran
ls runtime/backups/             # snapshots; newest 10 kept
```

Restore drill (do this once a season so you trust it):

```sh
bambo stop
bambo restore list                # pick a timestamp
bambo restore 20261021-033001
bambo start                       # verify the world in-game
# on success: rm -rf runtime/worlds.pre-restore-<stamp>
```

## Diagnostics

```sh
bambo doctor            # everything you'd check first, in one place
bambo health --json     # monitor-friendly
bambo-nettest           # LAN reachability probe (when joins fail)
```

Common failure → fix:

| Symptom | Likely cause | Fix |
|---|---|---|
| One device can't join, others can | client updated past protocol 2193 | align versions (see `docs/VERSIONS.md`) |
| Nobody can join | hotspot client isolation | `bambo-nettest`; make laptop the AP |
| `bambo stop` hangs | world save slow | it force-kills after 40s in cron contexts |
| Server died overnight | crash/restart loop | `logs/watchdog.log` if watchdog enabled; `runtime/logs/server.log` |
| `bambo setup` fails | GitHub API/network | retry; it resumes partial downloads |

## Maintenance

- **Version rollback**: `bambo setup 3.0.5` (or keep the previous jar, which setup preserves as
  `powernukkitx.jar.prev`).
- **Config**: `bambo config diff` shows drift from the tracked template; `bambo config set motd "X"`
  edits the live config safely (restart where needed, e.g. MOTD).
- **Ops**: `bambo op add <player>`; whitelist via `bambo whitelist …`.
- **Dashboard token**: `bambo dash token-new` (rotates; update any saved bookmark).

## systemd (optional)

Templates in `deploy/` — see the comment headers inside each unit file for install steps. Do not
mix tmux mode and systemd mode for the same instance.

## Monitoring suggestion (optional)

```sh
# every 5 min: alert if server is down (crontab)
*/5 * * * * cd /home/fiozxr/bambo-mc && ./bambo health --json | grep -q '"up":true' || logger -t bambo "server down"
```
