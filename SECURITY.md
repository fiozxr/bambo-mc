# Security

bambo-mc runs a **Minecraft server on a private LAN**. It is not a public internet service —
never expose it to the internet without a review of everything below.

## Trust model

- The game server (`runtime/`, PowerNukkitX) is reachable by anyone on your LAN **via UDP 19132**.
  With `xboxAuth: false` (default here), player identity is self-reported; this is acceptable for a
  trusted private group, not for a public server.
- The admin dashboard binds `127.0.0.1` by default and is token-gated. If you expose it on the LAN
  (`BAMBO_DASH_HOST=0.0.0.0`), **anyone on that network who knows the token can control the server**
  (including the raw `cmd` console pass-through).

## Secrets

- `dash.token` is auto-generated (32 hex chars) and mode `0600`. It is git-ignored — never commit it.
- You can override it without touching the file: `BAMBO_DASH_TOKEN=...`.
- Rotate it anytime: `bambo dash token-new`.

## Current mitigations

| Area | Measure |
|---|---|
| Dashboard auth | constant-time HMAC compare (`hmac.compare_digest`) |
| Dashboard abuse | per-IP rate limiting for failed auth attempts; request size cap |
| Dashboard transport | binds localhost by default; no TLS (planned for remote use) |
| Dashboard output | CSP + `X-Content-Type-Options` + `X-Frame-Options` headers; logs are rendered via `textContent` (no HTML injection) |
| Dashboard audit | every action is logged to `logs/dash-audit.log` (timestamp, IP, action, result) |
| Game server | `enableMetrics: false` (no bStats upstream); rate-limiting enabled in `pnx.yml` |
| Backups | snapshots are sha256/integrity-checked; restore keeps the pre-restore state |

## Reporting

This is a private project; report issues privately to the maintainers (not in public issues).
No bug-bounty program exists.

## Operational recommendations

1. Keep the OS and Java (21+) patched.
2. Keep `bambo doctor` clean; run `bambo health --json` from a cron/systemd timer to alert on outage.
3. Restore-drill: `bambo restore list` → restore a snapshot → verify → revert.
4. If the hotspot's client isolation is on, devices cannot reach each other — run `bambo-nettest`.
5. Never run `bambo start` from a public network without first understanding the exposure above.
