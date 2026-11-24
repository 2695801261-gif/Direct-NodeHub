# Cloudflare Workers WebSocket relay (optional)

This is an optional experiment, not a replacement for the direct node pool.

## What it can and cannot do

- Relays WebSocket traffic to one fixed HTTPS WebSocket upstream.
- Can only help nodes whose actual transport is WebSocket (for example, VLESS/WS or VMess/WS).
- Does not convert Shadowsocks, Trojan/TCP, Hysteria2, TUIC, raw TCP, or UDP into WebSocket.
- Does not make an upstream node faster, more reputable, or more available.
- The Worker can inspect the relayed protocol bytes. Do not use it for sensitive accounts or traffic.
- The origin hostname, TLS SNI, and WebSocket Host must be compatible. This Worker uses the upstream URL hostname for TLS and Host; nodes requiring a different WebSocket Host or SNI are not compatible with this version.
- Cloudflare Workers Free has request and CPU quotas. Long-lived WebSocket sessions may disconnect during runtime updates; clients must reconnect.

## Deploy

1. Create a Cloudflare Worker from the contents of 'worker-ws-relay.js'.
2. Add a Worker variable 'UPSTREAM_URL', for example 'https://origin.example:443/ws-path'. Use the exact upstream host, port and path from a candidate that has passed the Mihomo WebSocket protocol test.
3. Add a Worker secret 'RELAY_TOKEN' containing 24–128 random URL-safe characters (letters, numbers, underscore, hyphen). Do not commit the token or upstream details to GitHub.
4. Deploy the Worker and note its 'workers.dev' hostname.
5. Build a client config only after the selected upstream has passed testing. Client side must use VLESS/WS or VMess/WS with TLS to the Worker hostname and path '/<RELAY_TOKEN>'. Preserve the upstream UUID/password and any required VLESS flow only if compatible. Use the Worker hostname for SNI and Host.
6. Test from the actual mainland network. If it is slower or less stable than direct access, remove it from publication.

## Important limitations

The Worker URL is only a relay entrance. The exit IP and performance still belong to the upstream public node. This is not a residential-IP solution and does not create a residential egress address.

## Experimental WebSocket-to-TCP bridge (preferred experiment for raw TCP nodes)

The file `worker-ws-tcp-bridge.js` is a different relay mode from the WebSocket-to-WebSocket relay above. It accepts a client WebSocket, opens one fixed outbound TCP connection using Cloudflare's `cloudflare:sockets` API, and forwards the byte stream in both directions.

This can wrap a compatible **TLS TCP VLESS / VMess / Trojan** upstream in a client-side WebSocket connection. It does not require the upstream node itself to speak WebSocket.

### Supported and excluded

- Supported experiment: raw TCP VLESS or VMess with ordinary TLS; Trojan/TLS may also work if its upstream hostname and certificate are valid.
- Not supported: VLESS Reality, XTLS Vision / non-empty VLESS flow, Hysteria2, TUIC, UDP-only protocols, and upstream WebSocket transport.
- For TLS upstreams, the Worker connects to `UPSTREAM_HOST` and uses that hostname for TLS. The certificate must validate for that hostname; this bridge does not disable certificate verification or override SNI.
- The Worker is pinned to one upstream host and port. It is not an arbitrary open proxy.
- It does not change the exit IP, improve the upstream node's bandwidth, or turn a data-center IP into a residential IP.
- Client-to-Worker traffic is TLS-protected; Worker-to-upstream traffic is TLS-protected only when `UPSTREAM_TLS=true`.
- Cloudflare can still see the traffic at its Worker edge. Do not use it for sensitive accounts or private traffic.

### Deploy the TCP bridge

1. Create a separate Cloudflare Worker using the complete contents of `worker-ws-tcp-bridge.js`.
2. Add variables:
   - `UPSTREAM_HOST`: exact upstream domain name (not a URL).
   - `UPSTREAM_PORT`: upstream TCP port.
   - `UPSTREAM_TLS`: `true` for ordinary TLS upstreams; otherwise `false`.
3. Add secret `RELAY_TOKEN`: 24–128 random URL-safe characters (letters, numbers, underscore, hyphen). Never commit it to GitHub.
4. Deploy and note the Worker hostname.
5. The client-side proxy must use the original upstream protocol credentials, but point its server to the Worker hostname on port 443, use WebSocket transport, enable TLS to Cloudflare, and set the WebSocket path to `/<RELAY_TOKEN>`.
6. Test from the actual mainland network. Keep it only if it beats the direct upstream in real connection success, latency and stability.

The TCP bridge is an experiment. A successful syntax check is not a live connectivity test, and a Cloudflare-hosted test is not a mainland-China measurement.
