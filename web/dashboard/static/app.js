/* ================================================================
   ExoHand Live Dashboard — Frontend Logic  (v2 — debugged)
   ================================================================
   Handles WebSocket streaming, Chart.js live graph, connection
   management, prediction display, gesture history, and system logs.

   Fixes in v2:
   - WebSocket opens BEFORE connect returns to avoid data-drop race
   - Demo mode support via POST /api/demo
   - More visible UI log messages at every stage
   - Robust reconnect logic
   ================================================================ */

// ── Gesture accent colour map ────────────────────────────────────
const GESTURE_COLORS = {
    'thumb':        '#0060BB',
    'index':        '#5B3FA0',
    'middle':       '#A0416A',
    'fist':         '#B85A10',
    'rest':         '#5A6B7C',
    'pinky&ring':   '#8A2040',
    'calibrating':  '#6A7F94',
    'waiting':      '#8A9BAC',
    'disconnected': '#8A9BAC',
    'error':        '#B82020',
};

function gestureColor(name) {
    return GESTURE_COLORS[name?.toLowerCase()] || '#64748b';
}

// ── State ────────────────────────────────────────────────────────
let ws = null;
let chart = null;
let isConnected = false;
let isDemoMode = false;
let lastPrediction = '';
let pendingChartUpdate = false;
let messageCount = 0;

const MAX_CHART_POINTS  = 200;
const MAX_HISTORY_ITEMS = 10;
const MAX_LOG_ENTRIES   = 80;

// ── DOM references (cached on DOMContentLoaded) ──────────────────
let elPortSelect, elBaudInput, elBtnConnect, elBtnDisconnect, elBtnDemo;
let elBadge, elBadgeDot, elBadgeText;
let elGesture, elConfidenceText, elConfidenceBar, elPredictionCard, elPredictionStatus;
let elStatEmg, elStatPrediction, elStatConfidence, elStatWindow, elStatStatus;
let elHistory, elLogs;

// ── Initialisation ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Cache DOM references
    elPortSelect     = document.getElementById('port-select');
    elBaudInput      = document.getElementById('baud-input');
    elBtnConnect     = document.getElementById('btn-connect');
    elBtnDisconnect  = document.getElementById('btn-disconnect');
    elBtnDemo        = document.getElementById('btn-demo');
    elBadge          = document.getElementById('connection-badge');
    elBadgeDot       = elBadge.querySelector('.badge-dot');
    elBadgeText      = document.getElementById('connection-badge-text');
    elGesture        = document.getElementById('prediction-gesture');
    elConfidenceText = document.getElementById('prediction-confidence-text');
    elConfidenceBar  = document.getElementById('confidence-bar');
    elPredictionCard = document.getElementById('prediction-card');
    elPredictionStatus = document.getElementById('prediction-status');
    elStatEmg        = document.getElementById('stat-emg');
    elStatPrediction = document.getElementById('stat-prediction');
    elStatConfidence = document.getElementById('stat-confidence');
    elStatWindow     = document.getElementById('stat-window');
    elStatStatus     = document.getElementById('stat-status');
    elHistory        = document.getElementById('gesture-history');
    elLogs           = document.getElementById('system-logs');

    initChart();
    refreshPorts();
    addLog('Dashboard loaded. Select a serial port and click Connect.', 'info');
    addLog('Or click 🎮 Demo Mode to test without hardware.', 'info');
});

// ── Chart.js setup ───────────────────────────────────────────────
function initChart() {
    const ctx = document.getElementById('emg-chart').getContext('2d');

    const gradient = ctx.createLinearGradient(0, 0, 0, 240);
    gradient.addColorStop(0, 'rgba(0, 96, 187, 0.12)');
    gradient.addColorStop(1, 'rgba(0, 96, 187, 0.00)');

    chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'EMG Signal',
                data: [],
                borderColor: '#0060BB',
                backgroundColor: gradient,
                borderWidth: 1.5,
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                pointHitRadius: 0,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
                x: {
                    display: false,
                },
                y: {
                    grid: { color: 'rgba(10, 30, 60, 0.06)' },
                    ticks: {
                        color: '#7A8FA4',
                        font: { size: 11, family: 'Inter' },
                        maxTicksLimit: 6,
                    },
                    border: { color: '#C8D4E0' },
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: { enabled: false },
            },
            interaction: { enabled: false },
        }
    });
}

// ── Port management ──────────────────────────────────────────────
async function refreshPorts() {
    addLog('Refreshing serial ports…', 'info');
    try {
        const resp = await fetch('/api/ports');
        const data = await resp.json();
        elPortSelect.innerHTML = '<option value="">Select serial port…</option>';
        
        let recommendedPort = null;
        
        data.ports.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.device;
            
            let displayLabel = '';
            if (p.is_teensy) {
                displayLabel = `⚡ ${p.description} — ${p.device}`;
                if (!recommendedPort) recommendedPort = p.device;
            } else if (p.recommended) {
                displayLabel = `🔌 ${p.description} — ${p.device}`;
                if (!recommendedPort) recommendedPort = p.device;
            } else {
                displayLabel = `${p.device} — ${p.description}`;
            }
            
            opt.textContent = displayLabel;
            elPortSelect.appendChild(opt);
        });
        
        addLog(`✓ Ports refreshed: ${data.ports.length} found`, 'success');
        
        // Auto-select the first Teensy or USB recommended port if available
        if (recommendedPort) {
            elPortSelect.value = recommendedPort;
            addLog(`💡 Auto-selected recommended port: ${recommendedPort}`, 'info');
        }
        
        if (data.ports.length === 0) {
            addLog('⚠ No serial ports detected. Is Teensy plugged in?', 'warning');
        }
    } catch (e) {
        addLog('✗ Failed to refresh ports: ' + e.message, 'error');
    }
}

// ── Connect / Disconnect ─────────────────────────────────────────
async function connect() {
    const port = elPortSelect.value;
    const baud = parseInt(elBaudInput.value) || 115200;

    if (!port) {
        addLog('⚠ Select a serial port first.', 'warning');
        return;
    }

    elBtnConnect.disabled = true;
    if (elBtnDemo) elBtnDemo.disabled = true;
    addLog(`Connecting to ${port} @ ${baud} baud…`, 'info');

    // Step 1: Open the WebSocket FIRST so it's ready to receive data
    //         before the serial reader thread starts broadcasting
    addLog('Opening WebSocket connection…', 'info');
    const wsReady = await openWebSocket();
    if (!wsReady) {
        addLog('✗ WebSocket failed to open. Aborting connect.', 'error');
        elBtnConnect.disabled = false;
        if (elBtnDemo) elBtnDemo.disabled = false;
        return;
    }

    // Step 2: Now tell the backend to open serial and start the reader
    try {
        const resp = await fetch('/api/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ port, baud }),
        });
        const data = await resp.json();

        if (resp.ok) {
            addLog(`✓ Connected to ${port} at ${baud} baud`, 'success');
            addLog('Serial reader started — waiting for data…', 'info');
            isConnected = true;
            isDemoMode = false;
            updateConnectionUI(true);
        } else {
            addLog(`✗ ${data.error}`, 'error');
            closeWebSocket();
            elBtnConnect.disabled = false;
            if (elBtnDemo) elBtnDemo.disabled = false;
        }
    } catch (e) {
        addLog('✗ Connection error: ' + e.message, 'error');
        closeWebSocket();
        elBtnConnect.disabled = false;
        if (elBtnDemo) elBtnDemo.disabled = false;
    }
}

async function disconnect() {
    addLog('Disconnecting…', 'info');
    try {
        const resp = await fetch('/api/disconnect', { method: 'POST' });
        if (resp.ok) {
            addLog('✓ Disconnected from serial port.', 'success');
        }
    } catch (e) {
        addLog('Disconnect error: ' + e.message, 'error');
    }
    closeWebSocket();
    isConnected = false;
    isDemoMode = false;
    updateConnectionUI(false);
    resetPredictionCard();
}

// ── Demo mode ────────────────────────────────────────────────────
async function startDemo() {
    if (isConnected) {
        addLog('⚠ Already connected. Disconnect first.', 'warning');
        return;
    }

    addLog('Starting demo mode (fake EMG data)…', 'info');
    elBtnConnect.disabled = true;
    if (elBtnDemo) elBtnDemo.disabled = true;

    // Open WebSocket first
    const wsReady = await openWebSocket();
    if (!wsReady) {
        addLog('✗ WebSocket failed. Aborting demo.', 'error');
        elBtnConnect.disabled = false;
        if (elBtnDemo) elBtnDemo.disabled = false;
        return;
    }

    try {
        const resp = await fetch('/api/demo', { method: 'POST' });
        const data = await resp.json();

        if (resp.ok) {
            addLog('✓ Demo mode active — generating fake EMG values', 'success');
            isConnected = true;
            isDemoMode = true;
            updateConnectionUI(true, true);
        } else {
            addLog(`✗ ${data.error}`, 'error');
            closeWebSocket();
            elBtnConnect.disabled = false;
            if (elBtnDemo) elBtnDemo.disabled = false;
        }
    } catch (e) {
        addLog('✗ Demo error: ' + e.message, 'error');
        closeWebSocket();
        elBtnConnect.disabled = false;
        if (elBtnDemo) elBtnDemo.disabled = false;
    }
}

// ── WebSocket ────────────────────────────────────────────────────
function openWebSocket() {
    return new Promise((resolve) => {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${proto}//${location.host}/ws/live`;
        addLog(`WebSocket connecting to ${url}`, 'info');

        ws = new WebSocket(url);

        const timeout = setTimeout(() => {
            addLog('✗ WebSocket connection timed out (5 s)', 'error');
            ws.close();
            ws = null;
            resolve(false);
        }, 5000);

        ws.onopen = () => {
            clearTimeout(timeout);
            messageCount = 0;
            addLog('✓ WebSocket stream opened — ready for data', 'success');
            resolve(true);
        };

        ws.onclose = () => {
            clearTimeout(timeout);
            addLog('WebSocket stream closed.', 'info');
            if (isConnected) {
                addLog('Attempting WebSocket reconnect in 2 s…', 'warning');
                setTimeout(() => { if (isConnected) openWebSocket(); }, 2000);
            }
        };

        ws.onerror = (e) => {
            clearTimeout(timeout);
            addLog('✗ WebSocket error.', 'error');
            resolve(false);
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                messageCount++;
                // Log first 3 messages and then every 50th
                if (messageCount <= 3 || messageCount % 50 === 0) {
                    addLog(
                        `WS msg #${messageCount}: EMG=${data.raw_value} pred=${data.prediction} conf=${data.confidence}%`,
                        'info'
                    );
                }
                handleLiveData(data);
            } catch (e) {
                addLog('✗ Bad WebSocket message: ' + e.message, 'error');
            }
        };
    });
}

function closeWebSocket() {
    if (ws) {
        ws.onclose = null;   // prevent reconnect logic
        ws.close();
        ws = null;
    }
}

// ── Handle incoming live data ────────────────────────────────────
function handleLiveData(data) {
    // 1. Chart
    addChartPoint(data.raw_value);

    // 2. Prediction card
    updatePredictionCard(data);

    // 3. Stats
    updateStats(data);

    // 4. Connection lost from backend side
    if (data.connected === false) {
        if (data.prediction === 'disconnected' || data.prediction === 'error') {
            if (data.error) {
                addLog(`✗ Backend error: ${data.error}`, 'error');
            }
            isConnected = false;
            isDemoMode = false;
            updateConnectionUI(false);
            resetPredictionCard();
            closeWebSocket();
            return;
        }
    }

    // 5. Add to gesture history when prediction changes
    if (data.prediction !== 'calibrating' &&
        data.prediction !== 'waiting' &&
        data.prediction !== 'disconnected' &&
        data.prediction !== 'error' &&
        data.confidence > 0 &&
        data.prediction !== lastPrediction) {
        addHistory(data.prediction, data.confidence);
        lastPrediction = data.prediction;
    }
}

// ── Chart helpers ────────────────────────────────────────────────
function addChartPoint(value) {
    const ds = chart.data.datasets[0];
    chart.data.labels.push('');
    ds.data.push(value);

    if (ds.data.length > MAX_CHART_POINTS) {
        chart.data.labels.shift();
        ds.data.shift();
    }

    // Batch redraws to screen refresh rate for performance
    if (!pendingChartUpdate) {
        pendingChartUpdate = true;
        requestAnimationFrame(() => {
            chart.update('none');
            pendingChartUpdate = false;
        });
    }
}

function clearGraph() {
    chart.data.labels = [];
    chart.data.datasets[0].data = [];
    chart.update('none');
    addLog('Graph cleared.', 'info');
}

// ── Prediction card ──────────────────────────────────────────────
function updatePredictionCard(data) {
    const pred = data.prediction || 'waiting';
    const conf = data.confidence || 0;
    const color = gestureColor(pred);

    elGesture.textContent = pred.toUpperCase();
    elGesture.style.color = color;
    elConfidenceText.textContent = conf > 0 ? `${conf}%` : '—';
    elConfidenceText.style.color = color;
    elConfidenceBar.style.width = `${conf}%`;
    elConfidenceBar.style.background = color;

    // Update the left accent stripe colour via a CSS custom property
    elPredictionCard.style.setProperty('--stripe-color', conf > 0 ? color : 'var(--accent)');
    elPredictionCard.style.borderColor = conf > 0 ? `${color}55` : 'var(--border-color)';

    // Status text
    if (pred === 'calibrating') {
        const wc = data.window_count || 0;
        elPredictionStatus.textContent = `Calibrating window… [${wc}/30]`;
    } else if (pred === 'waiting' || pred === 'disconnected') {
        elPredictionStatus.textContent = 'Waiting for signal…';
    } else if (pred === 'error') {
        elPredictionStatus.textContent = 'Serial error occurred.';
    } else {
        const mode = data.demo ? 'Demo · ' : '';
        elPredictionStatus.textContent = `${mode}Majority-vote smoothed  ·  Live`;
    }
}

function resetPredictionCard() {
    elGesture.textContent = 'WAITING';
    elGesture.style.color = 'var(--text-muted)';
    elConfidenceText.textContent = '—';
    elConfidenceText.style.color = 'var(--text-secondary)';
    elConfidenceBar.style.width = '0%';
    elPredictionCard.style.borderColor = 'var(--border-color)';
    elPredictionCard.removeProperty?.('--stripe-color');
    elPredictionStatus.textContent = 'Waiting for signal…';
    lastPrediction = '';
}

// ── Stats ────────────────────────────────────────────────────────
function updateStats(data) {
    elStatEmg.textContent = data.raw_value ?? '—';
    elStatPrediction.textContent = data.prediction ? data.prediction.toUpperCase() : '—';
    elStatConfidence.textContent = data.confidence > 0 ? `${data.confidence}%` : '—';
    elStatWindow.textContent = `${data.window_count || 0} / 30`;

    // Status with colour
    elStatStatus.className = 'stat-value';
    if (data.connected) {
        if (data.window_ready) {
            elStatStatus.textContent = 'Predicting';
            elStatStatus.classList.add('status-connected');
        } else {
            elStatStatus.textContent = 'Calibrating';
            elStatStatus.classList.add('status-calibrating');
        }
    } else {
        elStatStatus.textContent = 'Disconnected';
        elStatStatus.classList.add('status-disconnected');
    }
}

// ── Gesture history ──────────────────────────────────────────────
function addHistory(gesture, confidence) {
    // Remove "empty" placeholder
    const empty = elHistory.querySelector('.history-empty');
    if (empty) empty.remove();

    const now = new Date();
    const ts = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const color = gestureColor(gesture);

    const el = document.createElement('div');
    el.className = 'history-item';
    el.style.borderLeftColor = color;
    el.innerHTML = `
        <span class="history-gesture" style="color:${color}">${gesture.toUpperCase()}</span>
        <span class="history-confidence">${confidence}%</span>
        <span class="history-time">${ts}</span>
    `;

    elHistory.prepend(el);

    // Cap at MAX_HISTORY_ITEMS
    while (elHistory.children.length > MAX_HISTORY_ITEMS) {
        elHistory.removeChild(elHistory.lastChild);
    }
}

function resetHistory() {
    elHistory.innerHTML = '<div class="history-empty">No predictions yet</div>';
    lastPrediction = '';
    addLog('Gesture history cleared.', 'info');
}

// ── System logs ──────────────────────────────────────────────────
function addLog(message, level = 'info') {
    // Defensive: if elLogs isn't ready yet, skip
    if (!elLogs) return;

    const now = new Date();
    const ts = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    const el = document.createElement('div');
    el.className = `log-entry log-${level}`;
    el.innerHTML = `<span class="log-time">${ts}</span>${escapeHtml(message)}`;

    elLogs.prepend(el);

    // Cap log entries
    while (elLogs.children.length > MAX_LOG_ENTRIES) {
        elLogs.removeChild(elLogs.lastChild);
    }
}

function clearLogs() {
    elLogs.innerHTML = '';
    addLog('Logs cleared.', 'info');
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── Connection UI toggle ─────────────────────────────────────────
function updateConnectionUI(connected, demo = false) {
    elBtnConnect.disabled = connected;
    elBtnDisconnect.disabled = !connected;
    elPortSelect.disabled = connected;
    elBaudInput.disabled = connected;
    if (elBtnDemo) elBtnDemo.disabled = connected;

    if (connected) {
        const label = demo ? 'Demo Mode' : 'Connected';
        elBadge.className = `badge badge-connected`;
        elBadgeText.textContent = label;
    } else {
        elBadge.className = `badge badge-disconnected`;
        elBadgeText.textContent = 'Disconnected';
    }
}
