const REFRESH_MS = 4000;

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function setCardState(card, entry, health) {
  const dot = card.querySelector('.dot');
  const label = card.querySelector('.state-label');
  const healthEl = card.querySelector('.health');
  const state = entry.state;

  if (state.running) {
    dot.dataset.state = 'running';
    label.textContent = `pid ${state.pid}`;
  } else if (state.error) {
    dot.dataset.state = 'error';
    label.textContent = state.error;
  } else if (state.exit_code !== null && state.exit_code !== undefined) {
    dot.dataset.state = 'stopped';
    label.textContent = `exited ${state.exit_code}`;
  } else {
    dot.dataset.state = 'idle';
    label.textContent = 'idle';
  }

  const running = Boolean(state.running);
  card.querySelector('.start').disabled = running;
  card.querySelector('.stop').disabled  = !running;
  card.querySelector('.logs').disabled  = !running;
  const openLink = card.querySelector('.btn-open');
  if (openLink) openLink.classList.toggle('disabled', !running);

  const crash = card.querySelector('.crash');
  if (crash) {
    if (!running && Array.isArray(state.crash_tail) && state.crash_tail.length) {
      crash.textContent = state.crash_tail.join('\n');
      crash.hidden = false;
    } else {
      crash.hidden = true;
    }
  }

  if (health) {
    if (health.ok) {
      healthEl.dataset.health = 'ok';
      healthEl.textContent = `health: ${health.status} · ${health.latency_ms}ms`;
    } else {
      healthEl.dataset.health = 'fail';
      healthEl.textContent = `health: ${health.error ? 'down' : health.status ?? 'unreachable'}`;
    }
  } else {
    healthEl.dataset.health = 'unknown';
    healthEl.textContent = 'health: —';
  }
}

async function refresh() {
  const [projectsResp, healthResp] = await Promise.all([
    api('/api/projects'),
    api('/api/health').catch(() => ({ results: {} })),
  ]);
  const results = healthResp.results || {};
  let running = 0;
  for (const entry of projectsResp.projects) {
    const card = document.querySelector(`.card[data-id="${entry.id}"]`);
    if (!card) continue;
    setCardState(card, entry, results[entry.id]);
    if (entry.state.running) running += 1;
  }
  document.getElementById('summary').textContent =
    `${running} running · ${projectsResp.projects.length} configured`;
  applyFilter();
}

function applyFilter() {
  const input = document.getElementById('search');
  const q = (input?.value || '').trim().toLowerCase();
  let visible = 0, total = 0;
  for (const card of document.querySelectorAll('.card')) {
    total += 1;
    const hit = !q || (card.dataset.search || '').includes(q);
    card.classList.toggle('hidden', !hit);
    if (hit) visible += 1;
  }
  if (q) {
    document.getElementById('summary').textContent =
      `${visible} of ${total} matching "${q}"`;
  }
}

const _logSockets = {};

function toggleLogStream(card) {
  const id = card.dataset.id;
  const view = card.querySelector('.logview');
  const btn = card.querySelector('.logs');

  if (_logSockets[id]) {
    _logSockets[id].close();
    return;
  }

  view.textContent = '';
  view.hidden = false;
  if (btn) btn.textContent = 'Logs ✕';

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/api/projects/${id}/logs/ws`);
  _logSockets[id] = ws;

  ws.onmessage = (ev) => {
    if (!ev.data) return; // keepalive ping
    view.textContent += ev.data + '\n';
    view.scrollTop = view.scrollHeight;
  };

  ws.onclose = () => {
    delete _logSockets[id];
    view.hidden = true;
    if (btn) btn.textContent = 'Logs';
  };

  ws.onerror = () => {
    view.textContent += '\n[stream error]';
  };
}

document.addEventListener('click', async (ev) => {
  const btn = ev.target.closest('button');
  if (!btn || btn.disabled) return;
  const card = btn.closest('.card');
  if (!card) {
    if (btn.id === 'refresh') refresh();
    return;
  }
  const id = card.dataset.id;
  try {
    if (btn.classList.contains('start')) {
      await api(`/api/projects/${id}/start`, { method: 'POST' });
      await refresh();
    } else if (btn.classList.contains('stop')) {
      if (_logSockets[id]) _logSockets[id].close();
      await api(`/api/projects/${id}/stop`, { method: 'POST' });
      await refresh();
    } else if (btn.classList.contains('logs')) {
      toggleLogStream(card);
    }
  } catch (err) {
    const label = card.querySelector('.state-label');
    if (label) label.textContent = `error: ${err.message}`;
  }
});

document.getElementById('search')?.addEventListener('input', applyFilter);

async function checkVersion() {
  const banner = document.getElementById('update-banner');
  if (!banner) return;
  try {
    const v = await api('/api/version');
    if (v.update_available) {
      const n = v.behind_by || 0;
      banner.textContent =
        `⬆ Update available — ${n} commit${n === 1 ? '' : 's'} behind. ` +
        `git pull && restart the wall.`;
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
  } catch {
    banner.hidden = true;
  }
}

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}

refresh();
checkVersion();
setInterval(refresh, REFRESH_MS);
setInterval(checkVersion, 120000);
