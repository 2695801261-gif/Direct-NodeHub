# Cloudflare Workers WebSocket relay (optional)

This is an optional experiment, not a replacement for the direct node pool.

## What it can and cannot do

- Relays WebSocket traffic to one fixed HTTPS WebSocket upstream.
- Can only help nodes whose actual transport is WebSocket (for example, VLESS/WS or VMess/WS).
- Does not convert Shadowsocks, Trojan/TCP, Hysteria2, TUIC, raw TCP, or UDP into WebSocket.
- Does not make an upstream node faster, more reputable, or more available.
- The Worker can inspect the relayed protocol bytes. Do not use it for sensitive accounts or traffic.
- The origin hostname, TLS SNI, and WebSocket Host must be compatible. Nodes using a front domain with a different Host/SNI are not automatically compatible with this simple fixed-origin relay.
- Cloudflare Workers Free has request and CPU quotas. Long-lived WebSocket sessions may disconnect during runtime updates; clients must reconnect.

## Deploy

1. Create a Cloudflare Worker from the contents of 'worker-ws-relay.js'.
2. Add a Worker variable 'UPSTREAM_URL', for example 'https://origin.example:443/ws-path'. Use the exact upstream host, port and path from a candidate that has passed the Mihomo WebSocket protocol test.
3. Add a Worker secret 'RELAY_TOKEN' containing a random value of at least 24 characters. Do not commit the token or upstream details to GitHub.
4. Deploy the Worker and note its 'workers.dev' hostname.
5. Build a client config only after the selected upstream has passed testing. Client side must use VLESS/WS or VMess/WS with TLS to the Worker hostname and path '/<RELAY_TOKEN>'. Preserve the upstream UUID/password and any required VLESS flow only if compatible. Use the Worker hostname for SNI and Host.
6. Test from the actual mainland network. If it is slower or less stable than direct access, remove it from publication.

## Important limitations

The Worker URL is only a relay entrance. The exit IP and performance still belong to the upstream public node. This is not a residential-IP solution and does not create a residential egress address.
