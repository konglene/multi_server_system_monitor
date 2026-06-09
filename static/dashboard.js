/* dashboard.js — sysmon real-time polling and history modal
 * Polls /api/servers every 10 seconds, updates cards in-place.
 * Opens a history modal with a mini chart on card click.
 * No external dependencies — plain ES6.
 */

'use strict';

// ─── Config ──────────────────────────────────────────────────────────────────
const POLL_INTERVAL_MS  = 10_000;   // match monitor.py sleep
const HISTORY_POINTS    = 20;       // /api/history returns last 20 rows
const WARN_THRESHOLD    = 80;       // % — orange bar
const CRIT_THRESHOLD    = 90;       // % — red bar

// ─── State ───────────────────────────────────────────────────────────────────
let pollTimer        = null;
let countdownTimer   = null;
let activeHistoryId  = null;        // server id whose modal is open

// ─── Boot ────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    buildGrid();           // first render from inline data (avoids flash)
    poll();                // then start live polling
    initModal();
});

// ─── Polling ─────────────────────────────────────────────────────────────────
async function poll() {
    setPollStatus('polling…', false);
    const ok = await fetchAndRender();
    if (ok) {
        startCountdown(Math.floor(POLL_INTERVAL_MS / 1000));
    } else {
        setPollStatus('poll error — retrying…', true);
    }
    pollTimer = setTimeout(poll, POLL_INTERVAL_MS);
}

async function fetchAndRender() {
    try {
        const res  = await fetch('/api/servers', { credentials: 'same-origin' });
        if (!res.ok) return false;
        const data = await res.json();
        renderCards(data);
        updateSummaryBar(data);
        return true;
    } catch (e) {
        console.warn('[sysmon] poll error:', e);
        return false;
    }
}

// ─── Countdown ────────────────────────────────────────────────────────────────
function startCountdown(totalSeconds) {
    clearInterval(countdownTimer);
    let remaining = totalSeconds;
    tick();
    countdownTimer = setInterval(() => {
        remaining = Math.max(0, remaining - 1);
        tick();
        if (remaining === 0) clearInterval(countdownTimer);
    }, 1000);

    function tick() {
        const el = document.getElementById('poll-status');
        if (!el) return;
        el.textContent = remaining > 0
            ? `next poll in ${remaining}s`
            : 'polling…';
        el.style.color = '';
    }
}

function setPollStatus(text, isError) {
    const el = document.getElementById('poll-status');
    if (!el) return;
    clearInterval(countdownTimer);
    el.textContent = text;
    el.style.color = isError ? 'var(--red, #f85149)' : '';
}

// ─── Grid ─────────────────────────────────────────────────────────────────────
// On first load the Jinja template renders cards server-side.
// We just make sure the grid container exists; subsequent polls reuse renderCards.
function buildGrid() {
    // Nothing to do — Jinja has already stamped out the initial cards.
    // We read them once to set up click handlers.
    document.querySelectorAll('.server-card').forEach(card => {
        card.addEventListener('click', () => {
            const id = card.dataset.serverId;
            openHistory(id);
        });
    });
}

// ─── Card Rendering ───────────────────────────────────────────────────────────
function renderCards(servers) {
    const grid = document.getElementById('server-grid');
    if (!grid) return;

    // Build a lookup of existing cards so we can update in-place
    const existing = {};
    grid.querySelectorAll('.server-card').forEach(el => {
        existing[el.dataset.serverId] = el;
    });

    // Track which ids came back so we can remove deleted servers
    const seen = new Set();

    servers.forEach((srv, idx) => {
        seen.add(String(srv.id));
        const m = srv.metrics || {};

        if (existing[srv.id]) {
            updateCard(existing[srv.id], srv, m);
        } else {
            const card = createCard(srv, m);
            card.style.animationDelay = `${idx * 60}ms`;
            grid.appendChild(card);
            card.addEventListener('click', () => openHistory(srv.id));
        }
    });

    // Remove cards for servers that no longer exist in DB
    Object.keys(existing).forEach(id => {
        if (!seen.has(id)) existing[id].remove();
    });

    // Empty state
    const empty = document.getElementById('empty-state');
    if (empty) empty.style.display = servers.length === 0 ? 'block' : 'none';
}

function createCard(srv, m) {
    const card = document.createElement('div');
    card.className = 'server-card';
    card.dataset.serverId = srv.id;
    card.innerHTML = cardInnerHTML(srv, m);
    return card;
}

function updateCard(card, srv, m) {
    // Swap status badge class without re-rendering the whole card (avoids flicker)
    const badge = card.querySelector('.status-badge');
    if (badge) {
        badge.textContent = srv.status;
        badge.className = `status-badge ${srv.status}`;
    }

    // Update metric values
    setCardText(card, '.metric-cpu   .metric-val', pct(m.cpu_percent));
    setCardText(card, '.metric-ram   .metric-val', pct(m.memory_percent));
    setCardText(card, '.metric-disk  .metric-val', pct(m.disk_percent));
    setCardText(card, '.metric-uptime .metric-val', formatUptime(m.uptime_seconds));

    // Update progress bars
    setBar(card, '.metric-cpu   .bar-fill', m.cpu_percent);
    setBar(card, '.metric-ram   .bar-fill', m.memory_percent);
    setBar(card, '.metric-disk  .bar-fill', m.disk_percent);

    // Pulse the card briefly on update if values changed
    card.classList.remove('just-updated');
    void card.offsetWidth;           // force reflow to restart animation
    card.classList.add('just-updated');
}

function setCardText(card, selector, value) {
    const el = card.querySelector(selector);
    if (el) el.textContent = value;
}

function setBar(card, selector, value) {
    const el = card.querySelector(selector);
    if (!el) return;
    const v = clamp(value ?? 0, 0, 100);
    el.style.width = `${v}%`;
    el.className = 'bar-fill ' + barClass(v);
}

function cardInnerHTML(srv, m) {
    const cpu    = m.cpu_percent    ?? 0;
    const ram    = m.memory_percent ?? 0;
    const disk   = m.disk_percent   ?? 0;
    const uptime = m.uptime_seconds ?? null;

    return `
        <div class="card-header">
            <div class="card-title-row">
                <span class="server-name">${esc(srv.name)}</span>
                <span class="status-badge ${srv.status}">${srv.status}</span>
            </div>
            <div class="server-meta">
                <span class="server-ip">${esc(srv.ip_address)}</span>
                <span class="os-badge">${esc(srv.os_type || 'linux')}</span>
            </div>
        </div>
        <div class="card-metrics">
            <div class="metric metric-cpu">
                <div class="metric-label">CPU</div>
                <div class="bar-track"><div class="bar-fill ${barClass(cpu)}" style="width:${clamp(cpu,0,100)}%"></div></div>
                <div class="metric-val">${pct(cpu)}</div>
            </div>
            <div class="metric metric-ram">
                <div class="metric-label">RAM</div>
                <div class="bar-track"><div class="bar-fill ${barClass(ram)}" style="width:${clamp(ram,0,100)}%"></div></div>
                <div class="metric-val">${pct(ram)}</div>
            </div>
            <div class="metric metric-disk">
                <div class="metric-label">DISK</div>
                <div class="bar-track"><div class="bar-fill ${barClass(disk)}" style="width:${clamp(disk,0,100)}%"></div></div>
                <div class="metric-val">${pct(disk)}</div>
            </div>
            <div class="metric metric-uptime">
                <div class="metric-label">UPTIME</div>
                <div class="metric-val uptime-val">${formatUptime(uptime)}</div>
            </div>
        </div>
        <div class="card-footer">
            <span class="last-seen">${srv.last_seen ? 'Last seen ' + relTime(srv.last_seen) : 'Never seen'}</span>
            <span class="card-hint">click for history</span>
        </div>
    `;
}

// ─── Summary bar (top of page) ────────────────────────────────────────────────
function updateSummaryBar(servers) {
    const total   = servers.length;
    const online  = servers.filter(s => s.status === 'online').length;
    const offline = total - online;

    setText('summary-total',   total);
    setText('summary-online',  online);
    setText('summary-offline', offline);

    // Average CPU across online servers
    const onlineSrvs = servers.filter(s => s.status === 'online' && s.metrics);
    if (onlineSrvs.length) {
        const avgCpu = onlineSrvs.reduce((a, s) => a + (s.metrics.cpu_percent ?? 0), 0) / onlineSrvs.length;
        setText('summary-avg-cpu', pct(avgCpu));
    } else {
        setText('summary-avg-cpu', '—');
    }
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
}

// ─── History Modal ────────────────────────────────────────────────────────────
function initModal() {
    const modal   = document.getElementById('history-modal');
    const overlay = document.getElementById('modal-overlay');
    if (!modal || !overlay) return;

    overlay.addEventListener('click', closeModal);

    document.getElementById('modal-close')?.addEventListener('click', closeModal);

    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeModal();
    });
}

async function openHistory(serverId) {
    const modal   = document.getElementById('history-modal');
    const overlay = document.getElementById('modal-overlay');
    if (!modal || !overlay) return;

    activeHistoryId = serverId;

    // Show loading state
    modal.querySelector('.modal-body').innerHTML = `
        <div class="modal-loading">
            <span class="blink">▍</span> fetching history...
        </div>
    `;

    modal.classList.add('open');
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';

    try {
        const res  = await fetch(`/api/history/${serverId}`, { credentials: 'same-origin' });
        const rows = await res.json();   // [{cpu_percent, memory_percent, disk_percent, recorded_at}, ...]
        renderHistoryChart(serverId, rows);
    } catch (e) {
        modal.querySelector('.modal-body').innerHTML =
            `<p class="modal-error">Failed to load history: ${esc(String(e))}</p>`;
    }
}

function closeModal() {
    document.getElementById('history-modal')?.classList.remove('open');
    document.getElementById('modal-overlay')?.classList.remove('open');
    document.body.style.overflow = '';
    activeHistoryId = null;
}

function renderHistoryChart(serverId, rows) {
    const modal = document.getElementById('history-modal');
    if (!modal) return;

    // Set the title from the card name if available
    const card     = document.querySelector(`.server-card[data-server-id="${serverId}"]`);
    const name     = card?.querySelector('.server-name')?.textContent || `Server #${serverId}`;
    const titleEl  = modal.querySelector('.modal-title');
    if (titleEl) titleEl.textContent = `${name} — last ${rows.length} samples`;

    const body = modal.querySelector('.modal-body');

    if (!rows || rows.length === 0) {
        body.innerHTML = `<p class="modal-error">No history data yet.</p>`;
        return;
    }

    // Build an SVG sparkline chart (CPU, RAM, Disk)
    const W = 680, H = 220, PAD = { top: 16, right: 16, bottom: 32, left: 40 };
    const innerW = W - PAD.left - PAD.right;
    const innerH = H - PAD.top  - PAD.bottom;

    const labels  = rows.map(r => r.recorded_at ? shortTime(r.recorded_at) : '');
    const cpuPts  = rows.map(r => r.cpu_percent    ?? 0);
    const ramPts  = rows.map(r => r.memory_percent ?? 0);
    const diskPts = rows.map(r => r.disk_percent   ?? 0);

    const n = rows.length;

    function xPos(i)   { return PAD.left + (i / (n - 1 || 1)) * innerW; }
    function yPos(val) { return PAD.top  + innerH - (clamp(val, 0, 100) / 100) * innerH; }

    function makePath(pts, klass) {
        if (pts.length === 0) return '';
        const d = pts.map((v, i) => `${i === 0 ? 'M' : 'L'}${xPos(i).toFixed(1)},${yPos(v).toFixed(1)}`).join(' ');
        return `<path class="chart-line ${klass}" d="${d}" fill="none" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    }

    function makeArea(pts, klass) {
        if (pts.length === 0) return '';
        const top    = pts.map((v, i) => `${i === 0 ? 'M' : 'L'}${xPos(i).toFixed(1)},${yPos(v).toFixed(1)}`).join(' ');
        const bottom = `L${xPos(n-1).toFixed(1)},${(PAD.top + innerH).toFixed(1)} L${PAD.left.toFixed(1)},${(PAD.top + innerH).toFixed(1)} Z`;
        return `<path class="chart-area ${klass}" d="${top} ${bottom}" stroke="none"/>`;
    }

    // Y-axis grid lines at 0, 25, 50, 75, 100
    const gridLines = [0, 25, 50, 75, 100].map(v => {
        const y = yPos(v).toFixed(1);
        return `
            <line class="chart-grid" x1="${PAD.left}" y1="${y}" x2="${PAD.left + innerW}" y2="${y}" stroke-dasharray="4 4"/>
            <text class="chart-axis-label" x="${PAD.left - 6}" y="${y}" text-anchor="end" dominant-baseline="middle">${v}</text>
        `;
    }).join('');

    // X-axis labels (show first, middle, last)
    const xLabels = [0, Math.floor((n - 1) / 2), n - 1].map(i => {
        const x = xPos(i).toFixed(1);
        const y = (PAD.top + innerH + 16).toFixed(1);
        return `<text class="chart-axis-label" x="${x}" y="${y}" text-anchor="middle">${esc(labels[i] || '')}</text>`;
    }).join('');

    // Hover dots — placed at each data point for the last row (most recent)
    const latestRow = rows[rows.length - 1];
    function dot(val, klass) {
        const x = xPos(n - 1).toFixed(1);
        const y = yPos(val).toFixed(1);
        return `<circle class="chart-dot ${klass}" cx="${x}" cy="${y}" r="4"/>`;
    }

    const svg = `
        <svg class="history-chart" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Metric history chart">
            ${gridLines}
            ${makeArea(cpuPts,  'area-cpu')}
            ${makeArea(ramPts,  'area-ram')}
            ${makeArea(diskPts, 'area-disk')}
            ${makePath(cpuPts,  'line-cpu')}
            ${makePath(ramPts,  'line-ram')}
            ${makePath(diskPts, 'line-disk')}
            ${dot(latestRow.cpu_percent    ?? 0, 'dot-cpu')}
            ${dot(latestRow.memory_percent ?? 0, 'dot-ram')}
            ${dot(latestRow.disk_percent   ?? 0, 'dot-disk')}
            ${xLabels}
        </svg>
    `;

    // Latest values snapshot
    const snap = `
        <div class="history-snapshot">
            <div class="snap-item cpu">
                <span class="snap-label">CPU</span>
                <span class="snap-val">${pct(latestRow.cpu_percent)}</span>
            </div>
            <div class="snap-item ram">
                <span class="snap-label">RAM</span>
                <span class="snap-val">${pct(latestRow.memory_percent)}</span>
            </div>
            <div class="snap-item disk">
                <span class="snap-label">DISK</span>
                <span class="snap-val">${pct(latestRow.disk_percent)}</span>
            </div>
        </div>
    `;

    const legend = `
        <div class="chart-legend">
            <span class="legend-item cpu">▬ CPU</span>
            <span class="legend-item ram">▬ RAM</span>
            <span class="legend-item disk">▬ DISK</span>
        </div>
    `;

    body.innerHTML = snap + svg + legend;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function pct(val) {
    if (val == null || isNaN(val)) return '—';
    return `${Math.round(val)}%`;
}

function clamp(v, min, max) {
    return Math.min(max, Math.max(min, v));
}

function barClass(v) {
    if (v >= CRIT_THRESHOLD) return 'bar-crit';
    if (v >= WARN_THRESHOLD) return 'bar-warn';
    return 'bar-ok';
}

function formatUptime(seconds) {
    if (seconds == null || seconds < 0) return '—';
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600)  / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

function relTime(isoStr) {
    // isoStr from Python's .isoformat() or DB string like "2024-01-15 12:34:56"
    if (!isoStr) return 'never';
    const date = new Date(isoStr.replace(' ', 'T'));
    if (isNaN(date)) return isoStr;
    const diff = Math.floor((Date.now() - date) / 1000);
    if (diff < 60)   return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400)return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

function shortTime(isoStr) {
    if (!isoStr) return '';
    const date = new Date(isoStr.replace(' ', 'T'));
    if (isNaN(date)) return isoStr;
    const hh = String(date.getHours()).padStart(2, '0');
    const mm = String(date.getMinutes()).padStart(2, '0');
    return `${hh}:${mm}`;
}

function esc(str) {
    // Minimal HTML escape for dynamic content
    return String(str)
        .replace(/&/g,  '&amp;')
        .replace(/</g,  '&lt;')
        .replace(/>/g,  '&gt;')
        .replace(/"/g,  '&quot;');
}