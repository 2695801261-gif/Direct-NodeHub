# Cloudflare relay code — research only, do not deploy on self-serve accounts

**Important: do not deploy these Workers as a VPN, proxy, or general traffic relay using a normal Cloudflare self-serve account.**

Cloudflare's Self-Serve Subscription Agreement, Section 2.2.1(j), says customers may not use its Services to provide "a virtual private network or other similar proxy services". This applies to the Workers relay experiments in this folder. Unless Cloudflare gives you explicit written permission or a different signed agreement that expressly allows this use, do not deploy or operate these Workers.

Official agreement:
https://www.cloudflare.com/terms/

## Why the code exists

The files are retained only as protocol/engineering research examples:

- `worker-ws-relay.js`: a fixed-origin WebSocket-to-WebSocket relay.
- `worker-ws-tcp-bridge.js`: an experimental fixed-origin WebSocket-to-TCP bridge using `cloudflare:sockets`.
- `tools/build-cloudflare-ws-config.py` and `tools/build-cloudflare-tcp-config.py`: local config-generation experiments.

A passing syntax check or a compatible upstream candidate does **not** mean the relay is permitted to deploy, has been deployed, or works from mainland China.

## Technical limits (research context only)

- The WebSocket relay can only wrap an upstream that already uses compatible TLS WebSocket transport.
- The TCP bridge only considers ordinary TLS TCP VLESS/VMess/Trojan candidates; it excludes Reality, XTLS Vision/flow, UDP, upstream WebSocket, custom TLS fingerprints and ALPN requirements, and port 25.
- Neither relay changes the upstream exit IP, creates a residential IP, or guarantees better speed or availability.
- Any relay operator may be able to inspect relayed traffic. Never send sensitive account, payment, or private traffic through untrusted infrastructure.

## Project decision

Cloudflare Workers are **not an active deployment path** for Direct-NodeHub under standard self-serve terms. The project prioritizes direct-node verification and actual mainland-network testing instead.
