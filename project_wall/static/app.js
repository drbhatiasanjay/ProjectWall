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
}

async function loadLogs(card) {
  const id = card.dataset.id;
  const view = card.querySelector('.logview');
  try {
    const data = await api(`/api/projects/${id}/logs?n=120`);
    view.textContent = data.lines.join('\n') || '(no logs yet)';
    view.hidden = false;
  } catch (err) {
    view.textContent = `error: ${err.message}`;
    view.hidden = false;
  }
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
      await api(`/api/projects/${id}/stop`, { method: 'POST' });
      await refresh();
    } else if (btn.classList.contains('logs')) {
      await loadLogs(card);
    }
  } catch (err) {
    const label = card.querySelector('.state-label');
    if (label) label.textContent = `error: ${err.message}`;
  }
});

refresh();
setInterval(refresh, REFRESH_MS);
