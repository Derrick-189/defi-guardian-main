/**
 * socket.js — SocketIO client for DeepGuard portal real-time updates
 */
(function () {
  'use strict';

  // ── Toast notification ───────────────────────────────────────────────────

  /**
   * Display a toast notification.
   * @param {string} title   - Bold heading text
   * @param {string} message - Body text
   * @param {string} type    - 'success' | 'danger' | 'info' | 'warning'
   * @param {number} [duration=5000] - Auto-dismiss delay in ms
   */
  function showToast(title, message, type, duration) {
    duration = duration || 5000;
    type = type || 'info';

    let container = document.querySelector('.flash-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'flash-container';
      document.body.appendChild(container);
    }

    const flash = document.createElement('div');
    flash.className = 'flash flash-' + type;

    const icon = _toastIcon(type);
    flash.innerHTML =
      '<span class="flash-icon">' + icon + '</span>' +
      '<div class="flash-body">' +
        (title ? '<strong>' + _escapeHtml(title) + '</strong> ' : '') +
        _escapeHtml(message) +
      '</div>' +
      '<button class="btn-icon flash-dismiss" aria-label="Dismiss" style="margin-left:auto;font-size:1rem;">×</button>';

    flash.querySelector('.flash-dismiss').addEventListener('click', function () {
      _removeFlash(flash);
    });

    container.appendChild(flash);

    const timer = setTimeout(function () {
      _removeFlash(flash);
    }, duration);

    flash._dismissTimer = timer;
  }

  function _removeFlash(el) {
    if (el._dismissTimer) clearTimeout(el._dismissTimer);
    el.style.transition = 'opacity 0.3s, transform 0.3s';
    el.style.opacity = '0';
    el.style.transform = 'translateX(100%)';
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 320);
  }

  function _toastIcon(type) {
    const icons = {
      success: '✓',
      danger: '✕',
      warning: '⚠',
      info: 'ℹ',
    };
    return icons[type] || icons.info;
  }

  function _escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Reconnection indicator ───────────────────────────────────────────────

  let _reconnectBanner = null;

  function _showReconnecting() {
    if (_reconnectBanner) return;
    _reconnectBanner = document.createElement('div');
    _reconnectBanner.id = 'dg-reconnect-banner';
    _reconnectBanner.style.cssText =
      'position:fixed;bottom:1rem;left:50%;transform:translateX(-50%);' +
      'background:var(--bg3);border:1px solid var(--warning);color:var(--warning);' +
      'padding:0.5rem 1.25rem;border-radius:6px;font-size:0.85rem;z-index:9998;' +
      'display:flex;align-items:center;gap:0.5rem;';
    _reconnectBanner.innerHTML =
      '<span class="spinner" style="width:14px;height:14px;border-width:2px;"></span>' +
      'Reconnecting…';
    document.body.appendChild(_reconnectBanner);
  }

  function _hideReconnecting() {
    if (_reconnectBanner) {
      _reconnectBanner.parentNode && _reconnectBanner.parentNode.removeChild(_reconnectBanner);
      _reconnectBanner = null;
    }
  }

  // ── SocketIO connection ──────────────────────────────────────────────────

  // Exponential backoff reconnection is handled by socket.io-client natively.
  // We configure it explicitly for clarity.
  const socket = io(window.location.origin, {
    transports: ['websocket', 'polling'],
    reconnection: true,
    reconnectionAttempts: Infinity,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 30000,
    randomizationFactor: 0.5,
  });

  // ── Event: connect ───────────────────────────────────────────────────────
  socket.on('connect', function () {
    _hideReconnecting();
    console.info('[DGSocket] Connected, socket id:', socket.id);
    socket.emit('request_state');
  });

  // ── Event: disconnect ────────────────────────────────────────────────────
  socket.on('disconnect', function (reason) {
    console.warn('[DGSocket] Disconnected:', reason);
    _showReconnecting();
  });

  // ── Event: reconnect_attempt ─────────────────────────────────────────────
  socket.on('reconnect_attempt', function (attempt) {
    console.info('[DGSocket] Reconnect attempt', attempt);
  });

  // ── Event: reconnect ─────────────────────────────────────────────────────
  socket.on('reconnect', function (attempt) {
    console.info('[DGSocket] Reconnected after', attempt, 'attempt(s)');
    _hideReconnecting();
  });

  // ── Event: verification_update ───────────────────────────────────────────
  socket.on('verification_update', function (data) {
    // Dispatch DOM custom event so any page can listen
    document.dispatchEvent(new CustomEvent('dg:state_update', { detail: data }));

    // Call global state handler if registered
    if (window.DGState && typeof window.DGState.onUpdate === 'function') {
      window.DGState.onUpdate(data);
    }
  });

  // ── Event: verification_complete ─────────────────────────────────────────
  socket.on('verification_complete', function (data) {
    // Dispatch DOM custom event
    document.dispatchEvent(new CustomEvent('dg:verification_complete', { detail: data }));

    // Show toast notification
    const tool = (data && data.tool) ? data.tool : 'Tool';
    const status = (data && data.status) ? data.status : 'unknown';
    const statusLower = status.toLowerCase();

    let type = 'info';
    if (statusLower === 'pass' || statusLower === 'verified') type = 'success';
    else if (statusLower === 'fail' || statusLower === 'violated') type = 'danger';
    else if (statusLower === 'timeout') type = 'warning';

    showToast(
      tool + ' — ' + status.toUpperCase(),
      (data && data.message) ? data.message : 'Verification run completed.',
      type
    );
  });

  // ── Event: connect_error ─────────────────────────────────────────────────
  socket.on('connect_error', function (err) {
    console.error('[DGSocket] Connection error:', err.message);
  });

  // ── Public API ───────────────────────────────────────────────────────────
  window.DGSocket = {
    socket: socket,
    showToast: showToast,
  };
})();
