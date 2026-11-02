# Version alignment

Bedrock clients and servers connect only when the protocol number matches. This file is the
map we use to decide which engine build to run.

## Current deployment

| | value |
|---|---|
| Engine | empty-serve (PowerNukkitX **3.0.5**) |
| Client version served | Bedrock **1.26.50** |
| Protocol | **2193** |
| Verified joined | phone at 10.92.202.32, 2026-10-16 |

## Upstream release → protocol map

Read from the release notes of `PowerNukkitX/PowerNukkitX` on 2026-10-17:

| PNX release | date | Bedrock | protocol |
|---|---|---|---|
| 2.0.0 | 2026-06-22 | 1.26.30 | — |
| 3.0.0 / 3.0.1 | 2026-07-26 / 29 | — | 1001 |
| 3.0.2 | 2026-08-05 | — | 2168 |
| 3.0.3 | 2026-08-14 | 1.26.44 | 2168 |
| 3.0.4 | 2026-08-29 | 1.26.45 | 2169 |
| **3.0.5** | **2026-09-15** | **1.26.50** | **2193** |
| branch `bedrock-1.26.60` | 2026-10-15 | 1.26.60 | (unreleased) |

Note the 3.0.2/3.0.3 pair shares protocol 2168 despite different version numbers, so client
version and protocol are not interchangeable facts. Trust the protocol column.

## Client versions obtainable on Linux

From the launcher's `mcbe-gdk-unpack-archive` catalog, stable channel, as of 2026-10-17:

```
1.26.50.4   <- matches our running engine (protocol 2193)
1.26.51.1
1.26.52.3   <- newest stable in the catalog
1.26.60.x / 1.26.70.x exist as BETA only
```

The laptop is currently pinned at 1.26.21.1, which is why it cannot join. `1.26.50.4` is the
exact release build of what the server speaks.

## When a device auto-updates past us

Symptom: that device alone can no longer join while the others still can.

Options, cheapest first:
1. Hold the updated client at a matching version if the launcher allows pinning.
2. Move everyone to the newest version the *other* clients already run, by choosing the PNX
   release whose protocol matches (see table).
3. Build upstream's `bedrock-1.26.60` branch and run that — requires the JDK, currently the
   one open blocker.
4. Switch to official BDS, which ships a new server the same day as the client. Cost: closed
   freeware, and no plugin ecosystem.

Rule of thumb: the **Windows Store device decides the target**, because it is the one client
that cannot be pinned or downgraded.
