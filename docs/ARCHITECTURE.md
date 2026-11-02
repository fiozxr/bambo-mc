# How bambo-mc works

## The problem this solves

Four players, one phone hotspot, no router with a fixed address, no port forwarding, no
public server. Bedrock's built-in "LAN world" does not survive that environment:

A hosted LAN world announces itself with **UDP broadcast/multicast** on ports 19132/19133.
Phone hotspots routinely drop client-to-client broadcast, so the world exists but no other
device ever sees the advertisement. That is the failure mode being worked around.

A **dedicated server** needs no broadcast. Each client connects to one known address, so the
discovery mechanism never comes into play. This is why the answer to "LAN worlds don't show
up" is not a better discovery tool but a server everyone points at directly.

## Data path

```
phone / Windows / Linux client
        |  UDP 19132  (Bedrock protocol, RakNet-compatible)
        v
   empty-serve (PowerNukkitX fork)  -- listens on *:19132
        |
        +-- worlds/    LevelDB-style chunk store
        +-- players/   LevelDB-style player profiles
        +-- plugins/   Bukkit-API plugins (org.powernukkitx package contract)
```

Only one UDP port is required. TCP 19133 is used for the optional sign server and can be
ignored on a LAN. There is no HTTP component, which is why nginx plays no role here — it
would only ever front a map/overview site, not the game.

## Address handling

The hotspot hands out changing leases, and this machine has moved between two different
networks during setup (`malware.sh` at 192.168.43.x, then `malware.py` at 10.92.202.x), so
no address is ever written down as config. `./bambo join` detects the current interface
address at run time. Two consequences worth remembering:

- A player's saved server entry goes stale whenever the laptop's lease changes.
- `ip` lives in `/usr/sbin`, outside cron's default PATH, which is why `bambo` sets its own.

## Authentication

`runtime/pnx.yml` sets `xboxAuth: false`. With it enabled, the server demands a valid Xbox
Live authentication chain from every connecting client, which means (a) clients must be
properly signed in *inside the game*, and (b) the server must reach Xbox's auth servers over
the internet to validate chains. On a private hotspot both are liabilities, so it is off.
The cost is that player identity is self-reported rather than verified — fine for four
family members, not fine for a public server.

`enableMetrics: false` stops bStats shipping server version, player count, OS and Java
version upstream; on this link it only produced DNS failures and stack traces in the log.

## Verified behaviour

Established by observation, not assumption:

- Device-to-device UDP traversal on this network **works** — a phone at 10.92.202.32
  connected to the laptop at 10.92.202.190 and played, with mobs and death events logged.
- The DTLS/identity handshake that third-party Bedrock servers use completes with real
  clients; a hand-crafted UDP probe is silently dropped, which is *why* only a genuine
  client can prove the server is joinable. Open port alone is not proof.
- World and player data survive a reboot. The machine rebooted mid-setup and the player
  store retained the previous session.
- PNX enforces one instance per data directory via `runtime/server.lock`. A hard kill can
  leave a stale lock, and the second-instance error is clear rather than corrupting data.

## Known limits

- **Protocol lock-in.** Release 3.0.5 accepts exactly protocol 2193 (Bedrock 1.26.50). A
  client that auto-updates past it is rejected. Upstream's `bedrock-1.26.60` branch is the
  escape route, which requires building from source.
- **One gamertag, one session.** Players are keyed by gamertag UUID, so two devices sharing
  an account displace each other.
- **No console operator yet.** `runtime/ops.txt` is empty, so nobody can run commands in-game.
## Operational additions (v2)

- **Pinned state** — `runtime/bambo.state.json` records the installed PNX tag, sha256,
  protocol and client version (written by `bambo setup`). This makes deployments
  reproducible and lets `bambo version`/`health` report the exact wire protocol.
- **Locking** — mutating operations (start/stop/backup/restore/setup) are serialized
  with `flock` on `runtime/.bambo.lock`, so the nightly cron and interactive use can
  never race.
- **Backup manifests** — each snapshot includes `manifest.json` (tool version, UTC
  timestamp, server tag, LevelDB CURRENT pointer) and is integrity-checked at creation.
- **Config drift** — `server/pnx.yml` is the tracked template; `bambo config`
  (get/set/diff/apply) keeps live `runtime/pnx.yml` inspectable and editable in a
  comment-preserving, YAML-safe way.
- **Watchdog** — `bambo watch` (opt-in) restarts a crashed server unless it was
  stopped intentionally (`runtime/.bambo.intentional-stop` marker set by `stop`,
  cleared by `start`).
- **Audit & request logs** — the dashboard writes JSON-lines audit entries
  (`logs/dash-audit.log`) and request logs (`logs/dash.log`).

