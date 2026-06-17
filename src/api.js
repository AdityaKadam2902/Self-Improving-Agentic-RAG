const BASE = '';

async function request(method, path, body, isForm = false) {
  const opts = { method, headers: {} };
  if (body) {
    if (isForm) {
      opts.body = body;
    } else {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
  }
  const res = await fetch(`${BASE}${path}`, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

/**
 * Stream a chat response via SSE.
 * Calls onToken(text) for each token, onDone(metadata) when complete,
 * onStatus(stage) for pipeline stage updates, onError(msg) on failure.
 */
export function streamChat(question, sessionId, { onToken, onStatus, onDone, onError }) {
  const controller = new AbortController();

  fetch(`${BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, session_id: sessionId }),
    signal: controller.signal,
  }).then(async (res) => {
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      onError && onError(err.detail || `HTTP ${res.status}`);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line

      let event = null;
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          event = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (event === 'token')  onToken  && onToken(data.text);
            if (event === 'status') onStatus && onStatus(data.stage);
            if (event === 'done')   onDone   && onDone(data);
            if (event === 'error')  onError  && onError(data.message);
          } catch {}
          event = null;
        }
      }
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onError && onError(err.message || 'Stream connection failed');
    }
  });

  return controller; // caller can call controller.abort() to cancel
}

export const api = {
  uploadDocument: (file) => {
    const form = new FormData();
    form.append('file', file);
    return request('POST', '/api/upload', form, true);
  },
  listDocuments:    ()       => request('GET',    '/api/documents'),
  deleteDocument:   (source) => request('DELETE', `/api/documents/${encodeURIComponent(source)}`),
  sendFeedback:     (payload) => request('POST',  '/api/feedback', payload),
  triggerImprovement: ()     => request('POST',   '/api/improve'),
  clearSession:     (id)     => request('DELETE', `/api/session/${id}`),
  health:           ()       => request('GET',    '/health'),
};