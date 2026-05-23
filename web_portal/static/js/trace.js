/**
 * trace.js — Trace viewer with playback controls for DeepGuard portal
 */
(function () {
  "use strict";

  // ── State ────────────────────────────────────────────────────────────────

  let _steps = [];
  let _currentIndex = -1;
  let _isPlaying = false;
  let _playInterval = null;
  let _playSpeed = 600; // ms between steps

  // ── Helpers ──────────────────────────────────────────────────────────────

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val !== undefined && val !== null ? val : "—";
  }

  function getAuditId() {
    // Try URL path segment: /trace/<audit_id>
    const match = window.location.pathname.match(/\/trace\/([^/]+)/);
    if (match) return match[1];
    // Fallback to global
    return window.DG_AUDIT_ID || "latest";
  }

  // ── Timeline rendering ───────────────────────────────────────────────────

  function renderTimeline(steps) {
    const container = document.getElementById("trace-timeline");
    if (!container) return;

    if (!steps || steps.length === 0) {
      container.innerHTML =
        '<div class="empty-state">' +
        '<span class="empty-state-icon">📭</span>' +
        '<div class="empty-state-title">No trace steps</div>' +
        '<div class="empty-state-desc">Run a verification to generate a trace.</div>' +
        "</div>";
      return;
    }

    container.innerHTML =
      '<div class="timeline">' +
      steps
        .map(function (step, idx) {
          const isError = step.is_error || step.error || false;
          const action = step.action || step.label || "(no action)";
          const proc = step.process || step.proc || "";
          const stepNum =
            step.step_num !== undefined
              ? step.step_num
              : step.step_number !== undefined
                ? step.step_number
                : idx;
          const vars = step.variables_after || step.variables || {};
          const varCount = Object.keys(vars).length;

          return (
            '<div class="timeline-item' +
            (isError ? " error" : "") +
            '" data-step-index="' +
            idx +
            '">' +
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;">' +
            "<div>" +
            '<span class="text-muted mono" style="font-size:0.75rem;">Step ' +
            escapeHtml(String(stepNum)) +
            "</span>" +
            (proc
              ? " <span style=\"color:var(--purple);font-size:0.75rem;font-family:'JetBrains Mono',monospace;\">[" +
                escapeHtml(proc) +
                "]</span>"
              : "") +
            '<div class="mono" style="font-size:0.85rem;margin-top:0.25rem;">' +
            escapeHtml(action) +
            "</div>" +
            "</div>" +
            (isError ? '<span class="badge badge-fail">ERROR</span>' : "") +
            "</div>" +
            (varCount > 0
              ? '<div class="text-muted" style="font-size:0.75rem;margin-top:0.4rem;">' +
                varCount +
                " variable" +
                (varCount !== 1 ? "s" : "") +
                " changed</div>"
              : "") +
            "</div>"
          );
        })
        .join("") +
      "</div>";

    // Click to jump to step
    container.querySelectorAll(".timeline-item").forEach(function (el) {
      el.addEventListener("click", function () {
        const idx = parseInt(el.getAttribute("data-step-index"), 10);
        goToStep(idx);
      });
    });
  }

  // ── Step navigation ──────────────────────────────────────────────────────

  function goToStep(idx) {
    if (idx < 0 || idx >= _steps.length) return;
    _currentIndex = idx;
    updateHighlight();
    updateStats();
    updateControls();
  }

  function stepForward() {
    if (_currentIndex < _steps.length - 1) {
      goToStep(_currentIndex + 1);
    } else {
      pause();
    }
  }

  function stepBackward() {
    if (_currentIndex > 0) {
      goToStep(_currentIndex - 1);
    }
  }

  function reset() {
    pause();
    goToStep(0);
  }

  function play() {
    if (_steps.length === 0) return;
    if (_currentIndex >= _steps.length - 1) {
      goToStep(0);
    }
    _isPlaying = true;
    updateControls();
    _playInterval = setInterval(function () {
      if (_currentIndex >= _steps.length - 1) {
        pause();
        return;
      }
      stepForward();
    }, _playSpeed);
  }

  function pause() {
    _isPlaying = false;
    if (_playInterval) {
      clearInterval(_playInterval);
      _playInterval = null;
    }
    updateControls();
  }

  function togglePlay() {
    if (_isPlaying) pause();
    else play();
  }

  // ── UI updates ───────────────────────────────────────────────────────────

  function updateHighlight() {
    const items = document.querySelectorAll(".timeline-item");
    items.forEach(function (el) {
      const idx = parseInt(el.getAttribute("data-step-index"), 10);
      el.classList.toggle("active", idx === _currentIndex);
    });

    // Scroll active item into view
    const active = document.querySelector(".timeline-item.active");
    if (active) {
      active.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  function updateStats() {
    const total = _steps.length;
    const current = _currentIndex >= 0 ? _currentIndex + 1 : 0;
    const errorCount = _steps.filter(function (s) {
      return s.is_error || s.error;
    }).length;

    setText("stat-total-steps", total);
    setText("stat-current-step", current + " / " + total);
    setText("stat-error-states", errorCount);

    // Count unique transitions (consecutive distinct actions)
    let transitions = 0;
    for (let i = 1; i < _steps.length; i++) {
      if ((_steps[i].action || "") !== (_steps[i - 1].action || ""))
        transitions++;
    }
    setText("stat-transitions", transitions);
  }

  function updateControls() {
    const playBtn = document.getElementById("btn-play");
    const pauseBtn = document.getElementById("btn-pause");
    const btnToggle = document.getElementById("btn-play-toggle");

    if (playBtn) playBtn.disabled = _isPlaying || _steps.length === 0;
    if (pauseBtn) pauseBtn.disabled = !_isPlaying;
    if (btnToggle) {
      btnToggle.textContent = _isPlaying ? "⏸" : "▶";
      btnToggle.setAttribute(
        "title",
        _isPlaying ? "Pause (Space)" : "Play (Space)",
      );
    }

    const fwdBtn = document.getElementById("btn-forward");
    const bwdBtn = document.getElementById("btn-backward");
    if (fwdBtn) fwdBtn.disabled = _currentIndex >= _steps.length - 1;
    if (bwdBtn) bwdBtn.disabled = _currentIndex <= 0;
  }

  // ── Speed slider ─────────────────────────────────────────────────────────

  function setupSpeedSlider() {
    const slider = document.getElementById("speed-slider");
    const label = document.getElementById("speed-label");
    if (!slider) return;

    // Slider goes 1–10 (matching the HTML); map to ms: 1=2000ms, 10=100ms
    slider.min = 1;
    slider.max = 10;
    slider.step = 1;
    slider.value = 5;
    _playSpeed = 600;

    if (label) label.textContent = _playSpeed + "ms";

    slider.addEventListener("input", function () {
      // Invert: higher slider value = faster = fewer ms
      _playSpeed = Math.round(2100 - parseInt(slider.value, 10) * 200);
      if (label) label.textContent = _playSpeed + "ms";

      if (_isPlaying) {
        clearInterval(_playInterval);
        _playInterval = setInterval(function () {
          if (_currentIndex >= _steps.length - 1) {
            pause();
            return;
          }
          stepForward();
        }, _playSpeed);
      }
    });
  }

  // ── Keyboard shortcuts ───────────────────────────────────────────────────

  function setupKeyboard() {
    document.addEventListener("keydown", function (e) {
      // Don't intercept when typing in inputs
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")
        return;

      switch (e.key) {
        case " ":
          e.preventDefault();
          togglePlay();
          break;
        case "ArrowRight":
          e.preventDefault();
          pause();
          stepForward();
          break;
        case "ArrowLeft":
          e.preventDefault();
          pause();
          stepBackward();
          break;
        case "r":
        case "R":
          e.preventDefault();
          reset();
          break;
        case "Home":
          e.preventDefault();
          pause();
          goToStep(0);
          break;
        case "End":
          e.preventDefault();
          pause();
          goToStep(_steps.length - 1);
          break;
      }
    });
  }

  // ── Button wiring ────────────────────────────────────────────────────────

  function setupButtons() {
    const btnPlayToggle = document.getElementById("btn-play-toggle");
    const btnPlay = document.getElementById("btn-play");
    const btnPause = document.getElementById("btn-pause");
    const btnForward = document.getElementById("btn-forward");
    const btnBackward = document.getElementById("btn-backward");
    const btnReset = document.getElementById("btn-reset");

    if (btnPlayToggle) btnPlayToggle.addEventListener("click", togglePlay);
    if (btnPlay) btnPlay.addEventListener("click", play);
    if (btnPause) btnPause.addEventListener("click", pause);
    if (btnForward)
      btnForward.addEventListener("click", function () {
        pause();
        stepForward();
      });
    if (btnBackward)
      btnBackward.addEventListener("click", function () {
        pause();
        stepBackward();
      });
    if (btnReset) btnReset.addEventListener("click", reset);
  }

  // ── Data loading ─────────────────────────────────────────────────────────

  function loadTrace(auditId) {
    const container = document.getElementById("trace-timeline");
    if (container) {
      container.innerHTML =
        '<div style="display:flex;justify-content:center;padding:3rem;">' +
        '<span class="spinner"></span>' +
        "</div>";
    }

    // Reset stats to loading state
    setText("stat-total-steps", "…");
    setText("stat-current-step", "…");
    setText("stat-error-states", "…");
    setText("stat-transitions", "…");

    const url = "/api/v1/trace/" + encodeURIComponent(auditId);

    fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) return Promise.reject("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        // API returns both "steps" and "trace" for compatibility
        _steps = data.steps || data.trace || [];
        renderTimeline(_steps);
        updateStats();
        updateControls();

        if (_steps.length > 0) {
          goToStep(0);
        }
      })
      .catch(function (err) {
        console.error("[Trace] Load failed:", err);
        setText("stat-total-steps", "—");
        setText("stat-current-step", "—");
        setText("stat-error-states", "—");
        setText("stat-transitions", "—");
        if (container) {
          container.innerHTML =
            '<div class="empty-state">' +
            '<span class="empty-state-icon">⚠️</span>' +
            '<div class="empty-state-title">Failed to load trace</div>' +
            '<div class="empty-state-desc">' +
            escapeHtml(String(err)) +
            "</div>" +
            "</div>";
        }
      });
  }

  // ── Init ─────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    const auditId = getAuditId();
    setupButtons();
    setupSpeedSlider();
    setupKeyboard();
    loadTrace(auditId);
  });
})();
