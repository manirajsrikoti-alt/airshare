/* AirShare Receiver Dashboard - Live updates */
(function () {
    'use strict';

    const transferArea = document.getElementById('transferArea');
    const placeholder = document.getElementById('placeholder');
    const receivingAnim = document.getElementById('receivingAnim');
    const screenshotDisplay = document.getElementById('screenshotDisplay');
    const screenshotImage = document.getElementById('screenshotImage');
    const senderName = document.getElementById('senderName');
    const receiveTime = document.getElementById('receiveTime');
    const historyList = document.getElementById('historyList');
    const statusBadge = document.getElementById('statusBadge');
    const statusText = document.getElementById('statusText');

    // Try SSE first, fall back to polling
    let useSSE = true;

    function showReceiving() {
        transferArea.className = 'transfer-area receiving';
        placeholder.classList.add('hidden');
        receivingAnim.classList.remove('hidden');
        screenshotDisplay.classList.add('hidden');
    }

    function showScreenshot(filename, sender, time) {
        screenshotImage.src = '/received/' + filename + '?t=' + Date.now();
        senderName.textContent = sender || 'Unknown';
        receiveTime.textContent = time || new Date().toLocaleTimeString();

        receivingAnim.classList.add('hidden');
        screenshotDisplay.classList.remove('hidden');
        transferArea.className = 'transfer-area received';
    }

    function updateHistory() {
        fetch('/api/recent')
            .then(r => r.json())
            .then(data => {
                if (!data.transfers || data.transfers.length === 0) {
                    historyList.innerHTML = '<p class="empty">No transfers yet</p>';
                    return;
                }
                historyList.innerHTML = data.transfers.map(t => `
                    <div class="history-item">
                        <span class="icon">🖼️</span>
                        <div class="details">
                            <div class="name">${escapeHtml(t.filename)}</div>
                            <div class="time">From ${escapeHtml(t.sender)} · ${escapeHtml(t.received_at)}</div>
                        </div>
                        <span class="badge">✓ Received</span>
                    </div>
                `).join('');
            })
            .catch(() => {});
    }

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function checkLatest() {
        fetch('/api/latest')
            .then(r => r.json())
            .then(data => {
                if (data.filename && data.exists) {
                    fetch('/api/status')
                        .then(r => r.json())
                        .then(status => {
                            showScreenshot(data.filename, null, null);
                            updateHistory();
                        });
                }
            })
            .catch(() => {});
    }

    // SSE connection
    function connectSSE() {
        const source = new EventSource('/api/events');
        source.onmessage = function (event) {
            try {
                const data = JSON.parse(event.data);
                if (data.event === 'new_transfer') {
                    showReceiving();
                    setTimeout(() => {
                        showScreenshot(data.filename, null, null);
                        updateHistory();
                    }, 1200);
                }
            } catch (e) {}
        };
        source.onerror = function () {
            useSSE = false;
            source.close();
            // Fall back to polling
            setInterval(checkLatest, 1500);
        };
    }

    function updatePeers() {
        fetch('/api/peers')
            .then(r => r.json())
            .then(data => {
                const peers = data.peers || [];
                const target = data.target;

                const pairedList = document.getElementById('peersList');
                if (pairedList) {
                    const paired = peers.filter(p => p.paired);
                    pairedList.innerHTML = paired.length === 0
                        ? '<p class="empty">No paired devices yet</p>'
                        : paired.map(p => `
                    <div class="peer-item">
                        <span class="icon">🔗</span>
                        <span class="name">${escapeHtml(p.name)}</span>
                    </div>
                `).join('');
                }

                const list = document.getElementById('discoveredList');
                if (list) {
                    list.innerHTML = peers.length === 0
                        ? '<p class="empty">No peers discovered yet</p>'
                        : peers.map(p => `
                    <div class="peer-item${p.peer_id === target ? ' is-target' : ''}">
                        <span class="icon">${p.paired ? '🔗' : '📡'}</span>
                        <span class="name">${escapeHtml(p.name)}</span>
                        <span class="sub">${escapeHtml(p.peer_id)}</span>
                        ${p.peer_id === target
                            ? '<span class="badge">✓ Target</span>'
                            : `<button class="target-btn" data-peer="${escapeHtml(p.peer_id)}">Select as target</button>`}
                    </div>
                `).join('');
                    list.querySelectorAll('.target-btn').forEach(btn => {
                        btn.addEventListener('click', () => selectTarget(btn.dataset.peer));
                    });
                }
            })
            .catch(() => {});
    }

    function selectTarget(peerId) {
        fetch('/api/target', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ peer_id: peerId }),
        })
            .then(r => r.json())
            .then(() => updatePeers())
            .catch(() => {});
    }

    function initGestureSwitch() {
        const sw = document.getElementById('gestureSwitch');
        const state = document.getElementById('gestureState');
        if (!sw) return;
        fetch('/api/gestures')
            .then(r => r.json())
            .then(data => {
                sw.checked = !!data.enabled;
                state.textContent = data.enabled ? 'ON' : 'OFF';
            })
            .catch(() => {});
        sw.addEventListener('change', () => {
            fetch('/api/gestures', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: sw.checked }),
            })
                .then(r => r.json())
                .then(data => {
                    sw.checked = !!data.enabled;
                    state.textContent = data.enabled ? 'ON' : 'OFF';
                })
                .catch(() => {});
        });
    }

    function updateMode() {
        fetch('/api/status')
            .then(r => r.json())
            .then(data => {
                const el = document.getElementById('modeInfo');
                if (el && data.mode === 'receiver-only') {
                    el.textContent = 'Receiver-only mode: camera unavailable, sending disabled.';
                }
            })
            .catch(() => {});
    }

    // Initial load
    checkLatest();
    updateHistory();
    updatePeers();
    initGestureSwitch();
    updateMode();

    // Start live updates
    connectSSE();

    // Also poll as backup
    setInterval(updateHistory, 5000);
    setInterval(updatePeers, 5000);
})();
