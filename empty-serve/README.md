# empty-serve

A Minecraft: Bedrock Edition server written from scratch. **MIT licensed** — this is
original code with no PowerNukkitX / Nukkit lineage, so it is genuinely yours to publish
under any terms.

It is **not finished.** Read the status honestly before deciding what to do with it.

## Status: milestone 4 (up to the encrypted handshake reply)

Layers built and **verified in isolation** (all original MIT, pure JDK, no PNX):

| Layer | Code | Self-test | Result |
|---|---|---|---|
| ping/pong server-list | `EsServer.java` | `handshake_probe.py` | pass |
| connection handshake OCR1/2→REPLY1/2 | `EsServer.java` | `handshake_probe.py` | pass |
| in-game framing + varint | `Framing.java` | `Framing.main` | 14/14 |
| P-384 keypair, ECDH, AES key | `Crypto.java` | `Crypto.main` | pass |
| connection key = SHA-256(token‖secret) | `Crypto.java` | both sides equal | pass |
| ES384 handshake JWT (DER↔raw sig) | `Handshake.java` | sign + verify + tamper-reject | pass |
| framed LOGIN → framed SERVER_TO_CLIENT_HANDSHAKE(id=3) w/ valid JWT | `EsServer`+`Handshake`+`Framing` | end-to-end probe | pass |

Constants sourced from **CloudburstMC/Protocol (Apache-2.0)** — packet IDs LOGIN=1,
PLAY_STATUS=2, SERVER_TO_CLIENT_HANDSHAKE=3, CLIENT_TO_SERVER_HANDSHAKE=4; key derivation
and JWT structure from its `EncryptionUtils`.

**Everything here is self-verified (my client ↔ my server). NONE of it is validated against a
real Minecraft client yet** — that is the actual wall and I can't cross it from a shell.

### What a real-client join still requires (unverified territory)

1. **Parse the LOGIN packet's JWT chain** to extract the client's ECDH public key. Without it
   we can't compute the shared secret, so the handshake reply above is structurally correct but
   cryptographically inert.
2. **Key confirmation + AES-CTR IV pairing** — the exact SHA-512/IV construction and the
   first-block counter quirk must match the client byte-for-byte or it drops the connection.
3. Then the **full game**: world, chunks, movement, blocks, entities, inventory, chat — weeks.

### How to validate with a real client (your move)

```
bash run-tests.sh          # build + all self-tests + probes
cd empty-serve && javac -d out src/esnet/*.java && java -cp out esnet.EsServer 19132
```

(only after stopping PNX, which owns 19132). Add `10.92.202.190:19132` on a phone. Expected
result today: the phone sends LOGIN, empty-serve replies with the handshake, then the client
disconnects because the encrypted session can't complete. **If even that reply appears in the
phone's attempt, milestones 1-4 are confirmed against a real client** — that's the next goal.

## The wall, stated plainly

After `0x08` a real client begins an **encrypted login**: Diffie-Hellman key exchange, a
**DTLS** handshake, an **AES-CTR** channel, and certificate/chain validation against an
`identity.pem` (P-384) the server must generate. empty-serve stops exactly there. Past it:
the `LOGIN` packet, then movement/blocks/items/entities/inventory/chat/crafting — the 60+
packet Bedrock surface — plus a **world** (region store, chunk NBT, generation).

That is a multi-week reverse-engineering project, not a single pass. Milestones 1-4 are a
real, tested foundation and prove the toolchain and approach work. They are not a playable
server.

## Build & run

```
bash run-tests.sh                 # everything at once (recommended)
javac -d out src/esnet/PingServer.java
java  -cp out esnet.PingServer 19134     # spare port; the live PNX server uses 19132
python3 probe.py 19134                   # structural round-trip test
```

## Relationship to the running server

The family's playable server is still **PowerNukkitX 3.0.5 in `../runtime/`** (see `../README.md`).
empty-serve does not replace it yet — nothing here accepts a game connection. Keep using PNX
to play while this grows, if it grows.

## On the earlier "make it unrecognisable" request

This is the legitimate version of that goal: new code you own, MIT, your own name on it.
What stayed out, on purpose, was pretending existing code was written from scratch when it
wasn't. This folder earns the MIT label by actually being new.

