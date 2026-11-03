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

    // Arrival toast per docs/animation-spec.md: slide-in thumbnail,
    // visible for TOAST_MS (2000), fade in 150 ms / fade out 300 ms.
    const TOAST_MS = 2000;
    const TOAST_FADE_IN_MS = 150;
    const TOAST_FADE_OUT_MS = 300;

    function showArrivalToast(filename) {
        const old = document.getElementById('arrivalToast');
        if (old) old.remove();

        const toast = document.createElement('div');
        toast.id = 'arrivalToast';
        toast.style.cssText = [
            'position:fixed', 'left:50%', 'bottom:32px',
            'transform:translate(-50%, 120%)',
            'display:flex', 'align-items:center', 'gap:10px',
            'background:rgba(20,20,20,0.92)', 'color:#eee',
            'padding:10px 16px', 'border-radius:10px',
            'border:2px solid #fff', 'z-index:9999',
            'box-shadow:0 4px 18px rgba(0,0,0,0.45)',
            'transition:transform ' + TOAST_FADE_IN_MS + 'ms ease-out, opacity ' + TOAST_FADE_OUT_MS + 'ms ease-in',
            'opacity:1', 'pointer-events:none',
        ].join(';');

        const thumb = document.createElement('img');
        thumb.src = '/received/' + filename + '?t=' + Date.now();
        thumb.alt = '';
        thumb.style.cssText = 'width:56px;height:42px;object-fit:cover;border-radius:4px;border:1px solid #fff';
        thumb.onerror = function () { thumb.style.display = 'none'; };

        const label = document.createElement('span');
        label.textContent = 'Screenshot received';

        toast.appendChild(thumb);
        toast.appendChild(label);
        document.body.appendChild(toast);

        requestAnimationFrame(() => {
            toast.style.transform = 'translate(-50%, 0)';
        });
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translate(-50%, 120%)';
            setTimeout(() => toast.remove(), TOAST_FADE_OUT_MS);
        }, TOAST_FADE_IN_MS + TOAST_MS);
    }

    // SSE connection
    function connectSSE() {
        const source = new EventSource('/api/events');
        source.onmessage = function (event) {
            try {
                const data = JSON.parse(event.data);
                if (data.event === 'new_transfer') {
                    showReceiving();
                    showArrivalToast(data.filename);
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
                        ${p.paired
                            ? '<span class="badge">✓ Paired</span>'
                            : `<span class="pair-controls">
                                 <input type="text" class="pin-input" maxlength="6" inputmode="numeric"
                                        placeholder="PIN" data-peer="${escapeHtml(p.peer_id)}">
                                 <button class="pair-btn" data-peer="${escapeHtml(p.peer_id)}">Pair</button>
                               </span>`}
                        ${p.peer_id === target
                            ? '<span class="badge">✓ Target</span>'
                            : `<button class="target-btn" data-peer="${escapeHtml(p.peer_id)}">Select as target</button>`}
                    </div>
                `).join('');
                    list.querySelectorAll('.target-btn').forEach(btn => {
                        btn.addEventListener('click', () => selectTarget(btn.dataset.peer));
                    });
                    list.querySelectorAll('.pair-btn').forEach(btn => {
                        btn.addEventListener('click', () => {
                            const input = list.querySelector(`.pin-input[data-peer="${btn.dataset.peer}"]`);
                            pairPeer(btn.dataset.peer, input ? input.value.trim() : '');
                        });
                    });
                }
            })
            .catch(() => {});
    }

    function pairPeer(peerId, pin) {
        if (!pin) { alert('Enter the 6-digit PIN shown on the peer.'); return; }
        fetch('/api/pair-peer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ peer_id: peerId, pin: pin }),
        })
            .then(r => r.json())
            .then(data => {
                if (!data.success) alert(data.error || 'Pairing failed');
                updatePeers();
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
