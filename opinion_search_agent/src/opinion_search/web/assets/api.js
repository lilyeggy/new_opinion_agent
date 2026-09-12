const JSON_HEADERS = { "Content-Type": "application/json" };

async function request(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: JSON_HEADERS,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = { error: text }; }
  }
  if (!response.ok) {
    const message = (payload && payload.error) || `请求失败（HTTP ${response.status}）`;
    throw new Error(message);
  }
  return payload;
}

export const api = {
  list: () => request("GET", "/api/investigations"),
  create: (payload) => request("POST", "/api/investigations", payload),
  snapshot: (id) => request("GET", `/api/investigations/${id}`),
  workbench: (id, snapshotId) => request("GET", `/api/investigations/${id}/workbench` +
    (snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "")),
  clarify: (id, answer) => request("POST", `/api/investigations/${id}/clarify`, { answer }),
  cancel: (id) => request("POST", `/api/investigations/${id}/cancel`, {}),
  resume: (id) => request("POST", `/api/investigations/${id}/resume`, {}),
  update: (id, payload) => request("POST", `/api/investigations/${id}/update`, payload),
  versions: (id) => request("GET", `/api/investigations/${id}/versions`),
  diff: (id, base) => request("GET", `/api/investigations/${id}/diff` + (base ? `?base=${encodeURIComponent(base)}` : "")),
  evidence: (id, evidenceId) => request("GET", `/api/investigations/${id}/evidence/${encodeURIComponent(evidenceId)}`),
  reportUrl: (id) => `/api/investigations/${id}/report`,
  pageUrl: (id, snapshotId) => `/api/investigations/${id}/page` +
    (snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : ""),
  pageDownloadUrl: (id, snapshotId) => `/api/investigations/${id}/page?download=1` +
    (snapshotId ? `&snapshot_id=${encodeURIComponent(snapshotId)}` : ""),
};

export const TERMINAL = new Set(["completed", "partial", "failed", "cancelled"]);

// Bounded reconnection for the snapshot stream. EventSource retries on its
// own, but the page also refetches a server snapshot so a network blip can
// never leave stale content frozen on screen.
const MAX_RECOVERY_ATTEMPTS = 5;
const RECOVERY_BACKOFF_MS = [1000, 2000, 4000, 8000, 16000];

export function stream(id, onSnapshot, onEnd, onConnection) {
  const source = new EventSource(`/api/investigations/${id}/events`);
  let closed = false;
  let recoveryAttempts = 0;
  let recoveryTimer = null;

  const close = () => {
    if (closed) return;
    closed = true;
    if (recoveryTimer) clearTimeout(recoveryTimer);
    source.close();
  };

  const refetchSnapshot = async () => {
    if (closed) return;
    try {
      const snapshot = await api.snapshot(id);
      if (closed) return;
      recoveryAttempts = 0;
      onConnection && onConnection("connected");
      onSnapshot(snapshot);
      if (TERMINAL.has(snapshot.status)) { close(); onEnd && onEnd("terminal"); }
    } catch {
      scheduleRecovery();
    }
  };

  const scheduleRecovery = () => {
    if (closed) return;
    if (recoveryAttempts >= MAX_RECOVERY_ATTEMPTS) {
      onConnection && onConnection("disconnected");
      close();
      onEnd && onEnd("error");
      return;
    }
    const delay = RECOVERY_BACKOFF_MS[Math.min(recoveryAttempts, RECOVERY_BACKOFF_MS.length - 1)];
    recoveryAttempts += 1;
    onConnection && onConnection("reconnecting");
    recoveryTimer = setTimeout(refetchSnapshot, delay);
  };

  source.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch { return; }
    if (data.type === "gone") { close(); onEnd && onEnd("gone"); return; }
    if (data.type !== "snapshot") return;
    recoveryAttempts = 0;
    onConnection && onConnection("connected");
    onSnapshot(data.snapshot);
    if (TERMINAL.has(data.snapshot.status)) { close(); onEnd && onEnd("terminal"); }
  };
  source.onopen = () => {
    recoveryAttempts = 0;
    onConnection && onConnection("connected");
  };
  source.onerror = () => {
    // A terminal stream closes on the server side; only a live page recovers.
    if (!closed) scheduleRecovery();
  };
  return { close };
}
