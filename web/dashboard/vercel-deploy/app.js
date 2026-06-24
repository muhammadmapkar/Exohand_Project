/* ================================================================
   ExoHand Live Dashboard — Vercel Static Deploy Edition
   ================================================================
   Self-contained frontend with:
   1. Browser-side Demo Engine (fake EMG simulation — no backend)
   2. Remote backend WebSocket connection option
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
let demoEngine = null;

const MAX_CHART_POINTS  = 200;
const MAX_HISTORY_ITEMS = 10;
const MAX_LOG_ENTRIES   = 80;

// ── DOM references (cached on DOMContentLoaded) ──────────────────
let elBackendUrl, elBtnConnect, elBtnDisconnect, elBtnDemo;
let elBadge, elBadgeDot, elBadgeText;
let elGesture, elConfidenceText, elConfidenceBar, elPredictionCard, elPredictionStatus;
let elStatEmg, elStatPrediction, elStatConfidence, elStatWindow, elStatStatus;
let elHistory, elLogs;

// ── Initialisation ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Cache DOM references
    elBackendUrl     = document.getElementById('backend-url');
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
    addLog('Dashboard loaded — running in standalone mode (Vercel).', 'info');
    addLog('Click ▶ Launch Simulation to see the demo, or connect to a backend.', 'info');
});

// ══════════════════════════════════════════════════════════════════
//  BROWSER-SIDE DEMO ENGINE
//  Generates realistic fake EMG data and predictions entirely in JS
// ══════════════════════════════════════════════════════════════════

class DemoEngine {
    constructor(onData) {
        this.onData = onData;
        this.running = false;
        this.intervalId = null;
        this.sampleCount = 0;
        this.startTime = 0;

        // Sliding window buffer
        this.windowSize = 30;
        this.window = [];
        this.predictEvery = 5;
        this.newSamples = 0;

        // Prediction state
        this.voteHistory = [];
        this.voteDepth = 5;
        this.lastPrediction = 'waiting';
        this.lastConfidence = 0;

        // Gesture profiles — matching the Python backend exactly
        this.gestures = [
            { name: 'rest',        baseline: 1854.5, amp: 15.0  },
            { name: 'fist',        baseline: 1854.5, amp: 300.0 },
            { name: 'thumb',       baseline: 1854.5, amp: 180.0 },
            { name: 'index',       baseline: 1854.5, amp: 120.0 },
            { name: 'pinky&ring',  baseline: 1854.5, amp: 60.0  },
            { name: 'middle',      baseline: 1854.5, amp: 150.0 },
        ];

        // Mapping amplitude ranges to gesture predictions
        // These thresholds roughly mimic what the RF model would produce
        this.gestureThresholds = [
            { name: 'rest',       minAmp: 0,   maxAmp: 30  },
            { name: 'pinky&ring', minAmp: 30,  maxAmp: 80  },
            { name: 'index',      minAmp: 80,  maxAmp: 140 },
            { name: 'middle',     minAmp: 140, maxAmp: 170 },
            { name: 'thumb',      minAmp: 170, maxAmp: 230 },
            { name: 'fist',       minAmp: 230, maxAmp: 500 },
        ];
    }

    start() {
        if (this.running) return;
        this.running = true;
        this.sampleCount = 0;
        this.startTime = performance.now();
        this.window = [];
        this.voteHistory = [];
        this.newSamples = 0;
        this.lastPrediction = 'calibrating';
        this.lastConfidence = 0;

        // Run at ~40 Hz (25ms interval) to match the broadcast throttle of the real backend
        this.intervalId = setInterval(() => this._tick(), 25);
    }

    stop() {
        this.running = false;
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }

        // Send final disconnected message
        this.onData({
            raw_value: 0,
            prediction: 'disconnected',
            confidence: 0,
            window_ready: false,
            connected: false,
            window_count: 0,
            timestamp: new Date().toISOString(),
        });
    }

    _gaussianRandom(mean, stddev) {
        // Box-Muller transform
        const u1 = Math.random();
        const u2 = Math.random();
        const z = Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
        return mean + z * stddev;
    }

    _tick() {
        const elapsed = (performance.now() - this.startTime) / 1000;
        // Rotate through gestures every 6 seconds
        const gestureIdx = Math.floor(elapsed / 6) % this.gestures.length;
        const gesture = this.gestures[gestureIdx];

        // Generate signal around baseline with gesture-specific amplitude
        let value = this._gaussianRandom(gesture.baseline, gesture.amp);
        value = Math.max(0, Math.round(value * 10) / 10);

        this.sampleCount++;

        // Add to window
        this.window.push(value);
        if (this.window.length > this.windowSize) {
            this.window.shift();
        }
        this.newSamples++;

        const windowReady = this.window.length >= this.windowSize;
        let prediction = this.lastPrediction;
        let confidence = this.lastConfidence;

        // Run prediction when window is full and enough new samples
        if (windowReady && this.newSamples >= this.predictEvery) {
            this.newSamples = 0;

            // Extract features from window
            const features = this._extractFeatures(this.window);

            // Simple amplitude-based classification (mimics the RF model)
            const result = this._classify(features);
            
            // Add to vote history
            this.voteHistory.push(result.gesture);
            if (this.voteHistory.length > this.voteDepth) {
                this.voteHistory.shift();
            }

            // Majority vote
            const voteCounts = {};
            for (const v of this.voteHistory) {
                voteCounts[v] = (voteCounts[v] || 0) + 1;
            }
            let maxVotes = 0;
            let winner = result.gesture;
            for (const [g, count] of Object.entries(voteCounts)) {
                if (count > maxVotes) {
                    maxVotes = count;
                    winner = g;
                }
            }

            prediction = winner;
            // Add realistic noise to confidence
            confidence = Math.min(99.5, Math.max(25, result.confidence + this._gaussianRandom(0, 5)));
            confidence = Math.round(confidence * 2) / 2; // Round to 0.5

            this.lastPrediction = prediction;
            this.lastConfidence = confidence;
        }

        if (!windowReady) {
            prediction = 'calibrating';
            confidence = 0;
        }

        // Emit data to the dashboard
        this.onData({
            raw_value:    value,
            prediction:   prediction,
            confidence:   confidence,
            window_ready: windowReady,
            connected:    true,
            window_count: this.window.length,
            timestamp:    new Date().toISOString(),
            demo:         true,
        });
    }

    _extractFeatures(win) {
        const arr = [...win];
        const n = arr.length;
        const mean = arr.reduce((a, b) => a + b, 0) / n;

        // MAV — Mean Absolute Value
        const mav = arr.reduce((a, b) => a + Math.abs(b), 0) / n;

        // RMS — Root Mean Square
        const rms = Math.sqrt(arr.reduce((a, b) => a + b * b, 0) / n);

        // Variance & Std
        const variance = arr.reduce((a, b) => a + (b - mean) ** 2, 0) / n;
        const std = Math.sqrt(variance);

        // WL — Waveform Length
        let wl = 0;
        for (let i = 1; i < n; i++) wl += Math.abs(arr[i] - arr[i - 1]);

        // ZCR — Zero Crossing Rate (relative to mean)
        let zcr = 0;
        const centered = arr.map(v => v - mean);
        for (let i = 1; i < n; i++) {
            if ((centered[i] >= 0) !== (centered[i - 1] >= 0)) zcr++;
        }

        // SSC — Slope Sign Changes
        let ssc = 0;
        for (let i = 2; i < n; i++) {
            const diff1 = arr[i] - arr[i - 1];
            const diff2 = arr[i - 1] - arr[i - 2];
            if ((diff1 > 0 && diff2 < 0) || (diff1 < 0 && diff2 > 0)) ssc++;
        }

        return { mav, rms, variance, std, wl, zcr, ssc };
    }

    _classify(features) {
        // Use standard deviation of the window as a proxy for signal amplitude
        // This is a simplified heuristic that mimics the RF model's behavior
        const amplitude = features.std;

        for (const t of this.gestureThresholds) {
            if (amplitude >= t.minAmp && amplitude < t.maxAmp) {
                // Base confidence: higher when amplitude is clearly within range
                const rangeCenter = (t.minAmp + t.maxAmp) / 2;
                const rangeDist = Math.abs(amplitude - rangeCenter) / ((t.maxAmp - t.minAmp) / 2);
                const baseConfidence = 90 - rangeDist * 30;
                return {
                    gesture: t.name,
                    confidence: Math.max(40, Math.min(97, baseConfidence)),
                };
            }
        }

        // Fallback — very high amplitude
        return { gesture: 'fist', confidence: 75 };
    }
}

// ══════════════════════════════════════════════════════════════════
//  CHART.JS SETUP
// ══════════════════════════════════════════════════════════════════

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

// ══════════════════════════════════════════════════════════════════
//  DEMO MODE (browser-side)
// ══════════════════════════════════════════════════════════════════

function startDemo() {
    if (isConnected) {
        addLog('⚠ Already running. Disconnect first.', 'warning');
        return;
    }

    addLog('Starting browser-side simulation…', 'info');

    demoEngine = new DemoEngine((data) => {
        handleLiveData(data);
    });

    demoEngine.start();
    isConnected = true;
    isDemoMode = true;
    messageCount = 0;
    updateConnectionUI(true, true);

    addLog('✓ Simulation active — generating fake EMG values in-browser', 'success');
    addLog('Gestures rotate every 6s: rest → fist → thumb → index → pinky&ring → middle', 'info');
}

// ══════════════════════════════════════════════════════════════════
//  BACKEND WEBSOCKET CONNECTION
// ══════════════════════════════════════════════════════════════════

function connectBackend() {
    if (isConnected) {
        addLog('⚠ Already connected. Disconnect first.', 'warning');
        return;
    }

    const url = elBackendUrl.value.trim();
    if (!url) {
        addLog('⚠ Enter a backend WebSocket URL first.', 'warning');
        return;
    }

    elBtnConnect.disabled = true;
    if (elBtnDemo) elBtnDemo.disabled = true;
    addLog(`Connecting to backend: ${url}`, 'info');

    openWebSocket(url);
}

function openWebSocket(url) {
    return new Promise((resolve) => {
        addLog(`WebSocket connecting to ${url}`, 'info');

        ws = new WebSocket(url);

        const timeout = setTimeout(() => {
            addLog('✗ WebSocket connection timed out (5 s)', 'error');
            ws.close();
            ws = null;
            elBtnConnect.disabled = false;
            if (elBtnDemo) elBtnDemo.disabled = false;
            resolve(false);
        }, 5000);

        ws.onopen = () => {
            clearTimeout(timeout);
            messageCount = 0;
            isConnected = true;
            isDemoMode = false;
            updateConnectionUI(true, false);
            addLog('✓ WebSocket stream opened — receiving live data from backend', 'success');
            resolve(true);
        };

        ws.onclose = () => {
            clearTimeout(timeout);
            addLog('WebSocket stream closed.', 'info');
            if (isConnected && !isDemoMode) {
                addLog('Attempting WebSocket reconnect in 2 s…', 'warning');
                setTimeout(() => {
                    if (isConnected && !isDemoMode) openWebSocket(url);
                }, 2000);
            }
        };

        ws.onerror = (e) => {
            clearTimeout(timeout);
            addLog('✗ WebSocket error — is the backend running?', 'error');
            elBtnConnect.disabled = false;
            if (elBtnDemo) elBtnDemo.disabled = false;
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

// ══════════════════════════════════════════════════════════════════
//  DISCONNECT (works for both demo and backend modes)
// ══════════════════════════════════════════════════════════════════

function disconnect() {
    addLog('Disconnecting…', 'info');

    if (isDemoMode && demoEngine) {
        demoEngine.stop();
        demoEngine = null;
        addLog('✓ Simulation stopped.', 'success');
    } else {
        closeWebSocket();
        addLog('✓ Disconnected from backend.', 'success');
    }

    isConnected = false;
    isDemoMode = false;
    updateConnectionUI(false);
    resetPredictionCard();
}

// ══════════════════════════════════════════════════════════════════
//  HANDLE INCOMING LIVE DATA (shared by demo + backend)
// ══════════════════════════════════════════════════════════════════

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
            if (demoEngine) {
                demoEngine.stop();
                demoEngine = null;
            }
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
        const mode = data.demo ? 'Simulation · ' : '';
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
    elPredictionCard.style.removeProperty?.('--stripe-color');
    elPredictionStatus.textContent = 'Click "Launch Simulation" to begin';
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
    if (elBackendUrl) elBackendUrl.disabled = connected;
    if (elBtnDemo) elBtnDemo.disabled = connected;

    if (connected) {
        const label = demo ? 'Simulation' : 'Connected';
        elBadge.className = `badge badge-connected`;
        elBadgeText.textContent = label;
    } else {
        elBadge.className = `badge badge-disconnected`;
        elBadgeText.textContent = 'Disconnected';
    }
}
