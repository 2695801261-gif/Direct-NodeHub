/**
 * Experimental WebSocket-to-TCP bridge for one fixed upstream node.
 *
 * This lets a VLESS/VMess/Trojan TCP stream travel inside a client WebSocket.
 * It does not support UDP, Reality, XTLS Vision, or upstream WebSocket transport.
 */
import { connect } from "cloudflare:sockets";

function closeSafely(socket, code = 1000, reason = "") {
  try {
    if (socket && socket.readyState < WebSocket.CLOSING) {
      const valid = code === 1000 || (Number.isInteger(code) && code >= 3000 && code < 5000);
      if (valid) socket.close(code, String(reason).slice(0, 100));
      else socket.close();
    }
  } catch (_) {}
}

async function toBytes(data) {
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  if (ArrayBuffer.isView(data)) return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  if (typeof Blob !== "undefined" && data instanceof Blob) {
    return new Uint8Array(await data.arrayBuffer());
  }
  if (typeof data === "string") return new TextEncoder().encode(data);
  throw new TypeError("Unsupported WebSocket message type");
}

function validHost(value) {
  const host = String(value || "").trim();
  if (!host || host.length > 253 || /[\s/@?#]/.test(host)) return false;
  return /^[A-Za-z0-9.:-]+$/.test(host);
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET") return new Response("Method not allowed", { status: 405 });
    const token = String(env.RELAY_TOKEN || "");
    if (!/^[A-Za-z0-9_-]{24,128}$/.test(token) ||
        request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
      return new Response("WebSocket bridge unavailable", { status: 404 });
    }
    const url = new URL(request.url);
    if (url.pathname !== "/" + token) return new Response("Not found", { status: 404 });

    const host = String(env.UPSTREAM_HOST || "").trim();
    const port = Number(env.UPSTREAM_PORT || 0);
    const useTls = String(env.UPSTREAM_TLS || "").toLowerCase() === "true";
    if (!validHost(host) || !Number.isInteger(port) || port < 1 || port > 65535 || port === 25) {
      return new Response("Invalid fixed upstream host or port", { status: 503 });
    }

    let upstream;
    try {
      upstream = connect(
        { hostname: host, port },
        { secureTransport: useTls ? "on" : "off", allowHalfOpen: true },
      );
      await upstream.opened;
    } catch (_) {
      try { await upstream?.close(); } catch (_) {}
      return new Response("Could not open fixed TCP upstream", { status: 502 });
    }

    const pair = new WebSocketPair();
    const client = pair[0];
    const server = pair[1];
    server.accept({ allowHalfOpen: true });
    server.binaryType = "arraybuffer";

    const writer = upstream.writable.getWriter();
    let closed = false;
    let writeQueue = Promise.resolve();

    const stop = (code = 1011, reason = "upstream bridge closed") => {
      if (closed) return;
      closed = true;
      closeSafely(server, code, reason);
      try { writer.releaseLock(); } catch (_) {}
      void upstream.close().catch(() => {});
    };

    server.addEventListener("message", (event) => {
      if (closed) return;
      writeQueue = writeQueue.then(async () => {
        if (closed) return;
        const bytes = await toBytes(event.data);
        await writer.write(bytes);
      }).catch(() => stop(1011, "upstream write failed"));
    });

    server.addEventListener("close", () => {
      if (closed) return;
      closed = true;
      void writeQueue
        .then(() => writer.close())
        .catch(() => {})
        .finally(() => upstream.close().catch(() => {}));
    });
    server.addEventListener("error", () => stop(1011, "client websocket error"));

    (async () => {
      const reader = upstream.readable.getReader();
      try {
        while (!closed) {
          const { value, done } = await reader.read();
          if (done) break;
          if (server.readyState !== WebSocket.OPEN) break;
          if (value && value.byteLength) server.send(value);
        }
        if (!closed) {
          closed = true;
          closeSafely(server, 1000, "upstream closed");
        }
      } catch (_) {
        stop(1011, "upstream read failed");
      } finally {
        try { reader.releaseLock(); } catch (_) {}
        try { writer.releaseLock(); } catch (_) {}
        await upstream.close().catch(() => {});
      }
    })();

    return new Response(null, {
      status: 101,
      webSocket: client,
      headers: { "Cache-Control": "no-store" },
    });
  },
};
