/**
 * Direct-NodeHub: optional Cloudflare Workers WebSocket relay.
 * Configure:
 *   UPSTREAM_URL = https://origin.example:443/websocket-path
 *   RELAY_TOKEN  = random token, at least 24 characters
 * WebSocket only; does not convert raw TCP or UDP to WebSocket.
 */
function closeSafely(socket, code = 1000, reason = "") {
  try {
    if (socket && socket.readyState < WebSocket.CLOSING) {
      // Keep close() compatible with strict WebSocket implementations:
      // only 1000 and application/private-use codes 3000-4999 are sent.
      const valid = code === 1000 || (Number.isInteger(code) && code >= 3000 && code < 5000 &&
        ![3004, 3005, 3006, 3015].includes(code));
      if (valid) socket.close(code, String(reason).slice(0, 100));
      else socket.close();
    }
  } catch (_) {}
}

function relay(source, destination) {
  source.addEventListener("message", (event) => {
    if (destination.readyState !== WebSocket.OPEN) return;
    try {
      destination.send(event.data);
    } catch (_) {
      closeSafely(source, 1011, "relay send failed");
      closeSafely(destination, 1011, "relay send failed");
    }
  });
  source.addEventListener("close", (event) => {
    closeSafely(destination, event.code, event.reason);
  });
  source.addEventListener("error", () => {
    closeSafely(destination, 1011, "upstream websocket error");
    closeSafely(source, 1011, "websocket relay error");
  });
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET") return new Response("Method not allowed", { status: 405 });
    const token = String(env.RELAY_TOKEN || "");
    if (!/^[A-Za-z0-9_-]{24,128}$/.test(token) ||
        request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
      return new Response("WebSocket relay unavailable", { status: 404 });
    }
    const url = new URL(request.url);
    if (url.pathname !== "/" + token) return new Response("Not found", { status: 404 });

    let upstreamUrl;
    try {
      upstreamUrl = new URL(String(env.UPSTREAM_URL || ""));
    } catch (_) {
      return new Response("Relay upstream is not configured", { status: 503 });
    }
    if (upstreamUrl.protocol !== "https:" || !upstreamUrl.hostname ||
        upstreamUrl.username || upstreamUrl.password) {
      return new Response("UPSTREAM_URL must be an HTTPS WebSocket origin URL", { status: 503 });
    }

    let upstreamResponse;
    try {
      upstreamResponse = await fetch(upstreamUrl.toString(), {
        headers: { Upgrade: "websocket" },
        redirect: "manual",
      });
    } catch (_) {
      return new Response("Could not reach WebSocket upstream", { status: 502 });
    }
    const upstream = upstreamResponse.webSocket;
    if (upstreamResponse.status !== 101 || !upstream) {
      return new Response("Upstream did not accept WebSocket", { status: 502 });
    }

    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1];
    server.accept({ allowHalfOpen: true });
    upstream.accept({ allowHalfOpen: true });
    server.binaryType = "arraybuffer";
    upstream.binaryType = "arraybuffer";
    relay(server, upstream);
    relay(upstream, server);

    return new Response(null, {
      status: 101,
      webSocket: client,
      headers: { "Cache-Control": "no-store" },
    });
  },
};
