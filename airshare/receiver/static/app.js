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
                const list = document.getElementById('peersList');
                if (!list) return;
                if (!data.peers || data.peers.length === 0) {
                    list.innerHTML = '<p class="empty">No paired devices yet</p>';
                    return;
                }
                list.innerHTML = data.peers.map(p => `
                    <div class="peer-item">
                        <span class="icon">🔗</span>
                        <span class="name">${escapeHtml(p.name)}</span>
                    </div>
                `).join('');
            })
            .catch(() => {});
    }

    // Initial load
    checkLatest();
    updateHistory();
    updatePeers();

    // Start live updates
    connectSSE();

    // Also poll as backup
    setInterval(updateHistory, 5000);
})();
