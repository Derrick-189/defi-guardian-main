/**
 * theme.js — Dark / light theme switcher for DeFi Guardian
 *
 * Applies data-theme="dark|light" to <html>.
 * Persists choice to localStorage and syncs to server.
 * Exposes window.DGTheme = { toggle, current, apply }.
 */
(function () {
  'use strict';

  var _theme = 'dark';

  // ── Apply theme ──────────────────────────────────────────────────────────
  function applyTheme(theme) {
    _theme = theme;
    // Set on <html> — this is what the CSS [data-theme="light"] selector targets
    document.documentElement.setAttribute('data-theme', theme);
    // Keep <body> in sync too (some rules may target body)
    if (document.body) {
      document.body.setAttribute('data-theme', theme);
    }
    _updateButtons(theme);
  }

  // ── Update button icons ──────────────────────────────────────────────────
  function _updateButtons(theme) {
    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      // Use Font Awesome classes rather than replacing innerHTML
      // so we don't destroy event listeners on child elements
      var icon = btn.querySelector('i');
      if (icon) {
        if (theme === 'dark') {
          icon.className = 'fa-solid fa-moon';
        } else {
          icon.className = 'fa-solid fa-sun';
        }
      } else {
        // Fallback: plain text emoji
        btn.textContent = theme === 'dark' ? '🌙' : '☀️';
      }
      btn.setAttribute('title',      theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
      btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
    });
  }

  // ── Toggle ───────────────────────────────────────────────────────────────
  function toggle() {
    var next = _theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    localStorage.setItem('dg-theme', next);

    // Sync to server (fire-and-forget)
    fetch('/api/set-theme', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme: next }),
      credentials: 'same-origin',
    }).catch(function () {});
  }

  // ── Resolve initial theme ────────────────────────────────────────────────
  function _resolveInitial() {
    var saved = localStorage.getItem('dg-theme');
    if (saved === 'dark' || saved === 'light') return saved;
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) return 'light';
    return 'dark';
  }

  // ── Apply immediately (before DOMContentLoaded) to avoid flash ───────────
  // We can set the attribute on <html> right now since it exists
  (function () {
    var initial = _resolveInitial();
    _theme = initial;
    document.documentElement.setAttribute('data-theme', initial);
  })();

  // ── Wire up buttons once DOM is ready ────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    // Re-apply to sync button icons (body now exists)
    applyTheme(_theme);

    // Single event delegation on document — avoids double-binding
    document.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-theme-toggle]');
      if (btn) {
        e.preventDefault();
        e.stopPropagation();
        toggle();
      }
    });

    // React to OS preference changes (only when no saved preference)
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', function (e) {
        if (!localStorage.getItem('dg-theme')) {
          applyTheme(e.matches ? 'light' : 'dark');
        }
      });
    }
  });

  // ── Public API ───────────────────────────────────────────────────────────
  window.DGTheme = {
    toggle:  toggle,
    current: function () { return _theme; },
    apply:   applyTheme,
  };

})();
