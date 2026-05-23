/**
 * counterexample.js — Three-panel counterexample viewer for DeepGuard portal
 * MINIMAL STABLE VERSION - Core functionality only
 */
(function () {
  "use strict";

  let _data = null;
  let _activeRuleIndex = null;
  let _activeStepIndex = null;
  let _filteredSteps = [];
  let _allSteps = [];
  let _useHex = false;

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatValue(val) {
    if (val === null || val === undefined) return "null";
    if (_useHex && typeof val === "number" && Number.isInteger(val)) {
      return "0x" + val.toString(16).toUpperCase();
    }
    return String(val);
  }

  function showSpinner(panelId) {
    const el = document.getElementById(panelId);
    if (el)
      el.innerHTML =
        '<div style="display:flex;justify-content:center;padding:2rem;"><span class="spinner"></span></div>';
  }

  function showError(panelId, message) {
    const el = document.getElementById(panelId);
    if (el) {
      el.innerHTML =
        '<div class="empty-state">' +
        '<span class="empty-state-icon">⚠️</span>' +
        '<div class="empty-state-title">Error</div>' +
        '<div class="empty-state-desc">' +
        escapeHtml(message) +
        "</div>" +
        "</div>";
    }
  }

  // ── Rules panel ──────────────────────────────────────────────────────────

  function renderRules(rules) {
    const panel = document.getElementById("rules-panel");
    if (!panel) return;

    if (!rules || rules.length === 0) {
      panel.innerHTML =
        '<div class="empty-state">' +
        '<span class="empty-state-icon">📋</span>' +
        '<div class="empty-state-title">No rules</div>' +
        "</div>";
      return;
    }

    panel.innerHTML = rules
      .map(function (rule, idx) {
        const status = (rule.status || "unknown").toLowerCase();
        const iconClass = ["verified", "violated", "timeout"].includes(status)
          ? status
          : "unknown";
        const formula = rule.formula || rule.ltl || "";

        return (
          '<div class="rule-item" data-rule-index="' +
          idx +
          '">' +
          '<span class="rule-icon ' +
          iconClass +
          '"></span>' +
          '<div class="rule-meta">' +
          '<div class="truncate rule-name">' +
          escapeHtml(rule.name || rule.id || "Rule " + (idx + 1)) +
          (rule.category ? ' <span style="color:var(--text2);font-size:0.75rem;">(' + escapeHtml(rule.category) + ')</span>' : '') +
          '</div>' +
          (formula
            ? '<div class="rule-formula" style="font-size:0.75rem;color:var(--text3);margin-top:0.2rem;word-break:break-word;">' +
              escapeHtml(formula) +
              '</div>'
            : '') +
          '</div>' +
          '</div>'
        );
      })
      .join("");

    panel.querySelectorAll(".rule-item").forEach(function (item) {
      item.addEventListener("click", function () {
        const idx = parseInt(item.getAttribute("data-rule-index"), 10);
        selectRule(idx);
      });
    });
  }

  function selectRule(idx) {
    _activeRuleIndex = idx;
    _activeStepIndex = null;

    document.querySelectorAll(".rule-item").forEach(function (el) {
      el.classList.toggle(
        "active",
        parseInt(el.getAttribute("data-rule-index"), 10) === idx,
      );
    });

    const rule = _data && _data.rules ? _data.rules[idx] : null;
    if (rule && rule.related_steps && rule.related_steps.length > 0) {
      _filteredSteps = _allSteps.filter(function (step) {
        const num = step.step !== undefined ? step.step : (step.step_number !== undefined ? step.step_number : step.index);
        return rule.related_steps.includes(num);
      });
    } else {
      _filteredSteps = _allSteps.slice();
    }

    renderTrace(_filteredSteps);
    renderVariables(null);
  }

  // ── Trace panel ──────────────────────────────────────────────────────────

  function renderTrace(steps) {
    const container = document.getElementById("trace-steps-container");
    if (!container) return;

    if (!steps || steps.length === 0) {
      container.innerHTML =
        '<div class="empty-state">' +
        '<span class="empty-state-icon">🔍</span>' +
        '<div class="empty-state-title">No trace steps</div>' +
        '<div class="empty-state-desc">The verification passed without violations, or this tool does not generate a step-by-step trace. Check the Raw Output tab for full tool output.</div>' +
        "</div>";
      return;
    }

    container.innerHTML = steps
      .map(function (step, displayIdx) {
        const stepNum =
          step.step !== undefined ? step.step : (step.step_number !== undefined ? step.step_number : displayIdx);
        const action = step.action || step.label || "";
        const proc = step.proc_name || step.process || step.proc || "";
        const isError = step.is_error || step.error || false;

        return (
          '<div class="trace-step' +
          (isError ? " error" : "") +
          '" data-step-display="' +
          displayIdx +
          '">' +
          '<span class="step-num">' +
          escapeHtml(String(stepNum)) +
          "</span>" +
          (step.line ? '<span class="step-line">L' + step.line + '</span>' : '') +
          (proc
            ? '<span class="step-proc">[' + escapeHtml(proc) + "]</span> "
            : "") +
          '<span class="step-action">' +
          escapeHtml(action) +
          "</span>" +
          "</div>"
        );
      })
      .join("");

    container.querySelectorAll(".trace-step").forEach(function (el) {
      el.addEventListener("click", function () {
        const idx = parseInt(el.getAttribute("data-step-display"), 10);
        if (Number.isNaN(idx)) return;
        _activeStepIndex = idx;
        container.querySelectorAll(".trace-step").forEach(function (item) {
          item.classList.toggle(
            "active",
            parseInt(item.getAttribute("data-step-display"), 10) === idx,
          );
        });
        const step = _filteredSteps[idx];
        if (step) {
          renderVariables(step);
          el.scrollIntoView({ block: "nearest", behavior: "smooth" });
          highlightStateMachineStep(idx);
          highlightSourceLine(step.line);
          
          // Auto-switch to variables panel if it's hidden or we're on mobile
          if (window.innerWidth < 768) {
            const panel = document.getElementById('panel-vars');
            if (panel) panel.scrollIntoView({ behavior: 'smooth' });
          }
        }
      });
    });
  }

  // ── Source Code panel ──────────────────────────────────────────────────

  function renderSourceCode(code, filename) {
    const pre = document.getElementById("source-code-pre");
    const fn = document.getElementById("source-filename");
    if (!pre) return;

    if (!code) {
      pre.innerHTML = '<div class="text-muted" style="padding:1rem;">Source code not available for this run.</div>';
      if (fn) fn.textContent = "";
      return;
    }

    if (fn) fn.textContent = filename || "contract.pml";

    const lines = code.split("\n");
    pre.innerHTML = lines
      .map(function (line, i) {
        return (
          '<div class="code-line" data-line="' + (i + 1) + '">' +
          '<span class="line-number">' + (i + 1) + '</span>' +
          '<span class="line-content">' + escapeHtml(line) + '</span>' +
          '</div>'
        );
      })
      .join("");
  }

  function highlightSourceLine(lineNum) {
    if (!lineNum) return;
    const pre = document.getElementById("source-code-pre");
    if (!pre) return;

    pre.querySelectorAll(".code-line").forEach(function (el) {
      el.classList.toggle("highlight", parseInt(el.getAttribute("data-line"), 10) === parseInt(lineNum, 10));
    });

    const active = pre.querySelector('.code-line.highlight');
    if (active) {
      active.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }

  // ── State Diagram panel ──────────────────────────────────────────────────

  function renderStateMachine(data) {
    const output = document.getElementById("state-machine-diagram");
    if (!output) return;

    const graph = data.state_graph || { nodes: [], edges: [] };
    const steps = data.trace_data && data.trace_data.steps ? data.trace_data.steps : [];
    
    if ((!graph.nodes || graph.nodes.length === 0) && steps.length === 0) {
      output.innerHTML = '<div class="text-muted" style="padding:2rem;text-align:center;">No graph data available</div>';
      return;
    }

    // Build mermaid syntax
    let lines = ['stateDiagram-v2'];
    
    // 1. Build from explicit graph if available
    if (graph.nodes && graph.nodes.length > 0) {
      const nodeIds = new Set();
      graph.nodes.forEach(n => {
        const id = String(n.id).replace(/[^a-zA-Z0-9_]/g, '');
        nodeIds.add(id);
        lines.push(`    state "${n.label || n.id}" as ${id}`);
        if (n.type === 'initial') lines.push(`    [*] --> ${id}`);
        if (n.type === 'error') lines.push(`    class ${id} failedState`);
      });
      
      (graph.edges || graph.links || []).forEach(e => {
        const sid = String(e.source || e.from).replace(/[^a-zA-Z0-9_]/g, '');
        const tid = String(e.target || e.to).replace(/[^a-zA-Z0-9_]/g, '');
        if (nodeIds.has(sid) && nodeIds.has(tid)) {
          lines.push(`    ${sid} --> ${tid}${e.label ? ' : ' + e.label : ''}`);
        }
      });
    } 
    // 2. Fallback: Build linear path from trace steps
    else if (steps.length > 0) {
      lines.push('    [*] --> Step0');
      steps.forEach((step, i) => {
        const label = step.action || step.label || `Step ${i}`;
        lines.push(`    state "${label}" as Step${i}`);
        if (i < steps.length - 1) {
          lines.push(`    Step${i} --> Step${i+1}`);
        }
        if (step.is_error || step.error) {
          lines.push(`    class Step${i} failedState`);
        }
      });
    }

    lines.push('    classDef failedState fill:#f85149,stroke:#fff,stroke-width:2px,color:#fff');
    lines.push('    classDef activeState stroke:#fff,stroke-width:4px,stroke-dasharray: 5 5');

    const code = lines.join('\n');
    try {
      output.removeAttribute('data-processed');
      output.innerHTML = code;
      if (window.mermaid) {
        window.mermaid.run({ 
          nodes: [output],
          postRender: function() {
            if (_activeStepIndex !== null) highlightStateMachineStep(_activeStepIndex);
          }
        });
      }
    } catch (e) {
      console.error('Mermaid render failed:', e);
    }
  }

  function highlightStateMachineStep(idx) {
    const svg = document.querySelector('#state-machine-diagram svg');
    if (!svg) return;
    
    // Remove previous highlights
    svg.querySelectorAll('.node').forEach(n => n.classList.remove('activeState'));
    
    // Add new highlight
    // If linear trace:
    const node = svg.querySelector(`#state-Step${idx}-0`) || svg.querySelector(`[id*="Step${idx}"]`);
    if (node) {
      node.classList.add('activeState');
      node.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  // ── Variables panel ──────────────────────────────────────────────────────

  function renderVariables(step) {
    const panel = document.getElementById("vars-panel");
    if (!panel) return;

    const before = step && step.variables_before ? step.variables_before : {};
    const after = step
      ? step.variables_after || step.variables || {}
      : _data && _data.final_variables
        ? _data.final_variables
        : {};

    const names = Array.from(
      new Set([...Object.keys(before), ...Object.keys(after)])
    ).sort();

    if (!names.length) {
      panel.innerHTML =
        '<div class="text-muted" style="padding:1rem;font-size:0.82rem;">No variables</div>';
      return;
    }

    // Grouping logic
    const groups = {};
    names.forEach(name => {
        const parts = name.split(/[:.]/);
        const groupName = parts.length > 1 ? parts[0] : "Global";
        if (!groups[groupName]) groups[groupName] = [];
        groups[groupName].push(name);
    });

    panel.innerHTML = Object.keys(groups).sort().map(groupName => {
        const groupHtml = groups[groupName].map(function (name) {
            const beforeVal = before[name];
            const afterVal = after[name];
            const changed = beforeVal !== undefined && beforeVal !== afterVal;
            const formattedBefore = formatValue(beforeVal);
            const formattedAfter = formatValue(afterVal);

            return (
              '<div class="var-row' + (changed ? ' changed' : '') + '">' +
              '<span class="var-name">' +
              escapeHtml(name) +
              '</span>' +
              '<span style="display:flex;gap:0.5rem;align-items:center;">' +
              (changed
                ? '<span class="var-before">' + escapeHtml(formattedBefore) + '</span>' +
                  '<span class="var-value var-changed">' + escapeHtml(formattedAfter) + '</span>'
                : '<span class="var-value">' + escapeHtml(formattedAfter) + '</span>') +
              '</span>' +
              '<button class="copy-btn" data-copy="' +
              escapeHtml(formattedAfter) +
              '" title="Copy value">⎘</button>' +
              '</div>'
            );
        }).join("");

        return (
            '<div class="var-group">' +
            '<div class="var-group-header">' + escapeHtml(groupName) + '</div>' +
            groupHtml +
            '</div>'
        );
    }).join("");

    panel.querySelectorAll(".copy-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const text = btn.getAttribute("data-copy");
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard
            .writeText(text)
            .then(function () {
              btn.textContent = "✓";
              setTimeout(function () {
                btn.textContent = "⎘";
              }, 1000);
            })
            .catch(function () {
              fallbackCopy(text);
            });
        } else {
          fallbackCopy(text);
        }
      });
    });
  }

  function fallbackCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }

  function renderWarnings(warnings) {
    const section = document.getElementById("warnings");
    const content = document.getElementById("warnings-content");
    if (!section || !content) return;
    
    if (!warnings || warnings.length === 0) {
      section.hidden = true;
      content.innerHTML = "";
      return;
    }
    
    section.hidden = false;
    content.innerHTML =
      '<ul class="diagnostic-list">' +
      warnings
        .map(function (warning) {
          return (
            '<li class="diagnostic-item warning-item">' +
            '<i class="fa-solid fa-triangle-exclamation"></i>' +
            '<span>' + escapeHtml(warning) + '</span>' +
            '</li>'
          );
        })
        .join("") +
      '</ul>';
  }

  function renderRecommendations(recommendations) {
    const section = document.getElementById("recommendations");
    const content = document.getElementById("recommendations-content");
    if (!section || !content) return;
    
    if (!recommendations || recommendations.length === 0) {
      section.hidden = true;
      content.innerHTML = "";
      return;
    }
    
    section.hidden = false;
    content.innerHTML =
      '<ul class="diagnostic-list">' +
      recommendations
        .map(function (rec) {
          return (
            '<li class="diagnostic-item rec-item">' +
            '<i class="fa-solid fa-arrow-right"></i>' +
            "<span>" +
            escapeHtml(rec) +
            "</span>" +
            "</li>"
          );
        })
        .join("") +
      "</ul>";
  }

  function setupSearch() {
    const searchInput = document.getElementById("trace-search");
    if (!searchInput) return;

    searchInput.addEventListener("input", function () {
      const query = searchInput.value.trim().toLowerCase();
      if (!query) {
        _filteredSteps = _allSteps.slice();
      } else {
        _filteredSteps = _allSteps.filter(function (step) {
          const action = (step.action || step.label || "").toLowerCase();
          const proc = (step.process || step.proc || "").toLowerCase();
          return action.includes(query) || proc.includes(query);
        });
      }
      _activeStepIndex = null;
      renderTrace(_filteredSteps);
    });
  }

  function setupHexToggle() {
    const btn = document.getElementById("hex-toggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      _useHex = !_useHex;
      btn.textContent = _useHex ? "DEC" : "HEX";
      const step =
        _activeStepIndex !== null ? _filteredSteps[_activeStepIndex] : null;
      renderVariables(step);
    });
  }

  function _updateHeader(data) {
    var fnEl = document.querySelector(".audit-filename");
    if (fnEl && data.filename) {
      fnEl.innerHTML =
        '<i class="fa-solid fa-file-code"></i> ' + escapeHtml(data.filename);
    }

    // Download button logic
    const dlBtn = document.getElementById('download-trail-btn');
    if (dlBtn) {
      if (data.job_id && data.tool && data.tool.toLowerCase() === 'spin' && data.status === 'FAIL') {
        dlBtn.hidden = false;
        dlBtn.onclick = function() {
          // Trail file is usually contract.pml.trail or similar
          // We'll try to get it from report_path if it was provided, or default to common names
          let trailName = 'contract.pml.trail';
          window.location.href = '/api/v1/artifact/' + data.job_id + '/' + trailName;
        };
      } else {
        dlBtn.hidden = true;
      }
    }

    var infoEl = document.querySelector(".audit-info");
    if (infoEl) {
      infoEl.querySelectorAll(".dyn-badge").forEach(function (b) {
        b.remove();
      });
      if (data.tool) {
        var tb = document.createElement("span");
        tb.className = "badge badge-tool dyn-badge";
        tb.textContent = data.tool;
        infoEl.appendChild(tb);
      }
      if (data.status) {
        var s = (data.status || "").toUpperCase();
        var sb = document.createElement("span");
        sb.className =
          "badge dyn-badge " +
          (s === "PASS"
            ? "badge-pass"
            : s === "FAIL"
              ? "badge-fail"
              : "badge-tool");
        sb.textContent = s;
        infoEl.appendChild(sb);
      }
    }

    // Update the SPIN switch banner whenever tool/filename changes
    if (typeof _updateSpinBanner === "function") {
      _updateSpinBanner(data.tool || "", data.filename || "");
    }
  }

  function _updateStats(data) {
    function set(id, v) {
      const el = document.getElementById(id);
      if (el) el.textContent = (v !== undefined && v !== null) ? v : "—";
    }

    // API returns a nested "stats" object AND top-level fields for back-compat
    const stats = data.stats || {};
    set("ce-stat-states", stats.states      ?? data.states_explored ?? data.states      ?? "—");
    set("ce-stat-trans",  stats.transitions ?? data.transitions                          ?? "—");
    set("ce-stat-depth",  stats.depth       ?? data.depth_reached   ?? data.depth        ?? "—");

    if (data.ltl_properties) {
      set("ce-stat-rules", data.ltl_properties.length);
      const violations = data.ltl_properties.filter(function (r) {
        return (r.status || "").toUpperCase() === "VIOLATED";
      }).length;
      const vEl = document.getElementById("ce-stat-violations");
      if (vEl) {
        vEl.textContent = violations;
        vEl.className = "value " + (violations > 0 ? "text-danger" : "text-success");
      }
    }
  }

  function loadData(auditId) {
    showSpinner("rules-panel");
    showSpinner("trace-steps-container");
    showSpinner("vars-panel");

    const url =
      auditId === "latest"
        ? "/api/v1/counterexample/latest"
        : "/api/v1/counterexample/" + encodeURIComponent(auditId);

    fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) return Promise.reject("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        _data = data;
        _allSteps =
          data.trace_data && data.trace_data.steps ? data.trace_data.steps : [];
        _filteredSteps = _allSteps.slice();

        var rules = data.ltl_properties || data.rules || [];
        rules = rules.map(function (r) {
          if (!r.status) {
            r.status =
              r.success === true || r.errors === 0 ? "VERIFIED" : "VIOLATED";
          }
          return r;
        });
        _data.rules = rules;

        _updateHeader(data);
        _updateStats(data);

        renderRules(rules);
        renderTrace(_filteredSteps);
        renderStateMachine(data);
        renderSourceCode(data.source_code, data.filename);
        selectInitialStep();
        renderRecommendations(data.recommendations || []);
        renderWarnings(
          data.unreached_states ||
          (data.trace_data && data.trace_data.warnings) ||
          []
        );

        var rawPre = document.getElementById("raw-output-pre");
        if (rawPre) rawPre.textContent = data.output || "(no raw output)";
      })
      .catch(function (err) {
        console.error("[Counterexample] Load failed:", err);
        showError("rules-panel", "Failed to load rules");
        showError("trace-steps-container", "Error loading trace: " + String(err));
        showError("vars-panel", "No data available");
      });
  }

  function selectInitialStep() {
    if (!_filteredSteps || _filteredSteps.length === 0) return;
    var preferred = _filteredSteps.findIndex(function (step) {
      return step.is_error || step.error;
    });
    var idx = preferred >= 0 ? preferred : 0;
    _activeStepIndex = idx;
    var traceNodes = document.querySelectorAll(".trace-step");
    traceNodes.forEach(function (item) {
      item.classList.toggle(
        "active",
        parseInt(item.getAttribute("data-step-display"), 10) === idx,
      );
    });
    var step = _filteredSteps[idx];
    if (step) {
      renderVariables(step);
      var active = traceNodes[idx];
      if (active && active.scrollIntoView) {
        active.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    }
  }

  // ── SPIN switch banner ───────────────────────────────────────────────────

  // allRuns is populated after populateRunSelector loads.
  var _allRuns = [];
  var _currentTool = null;
  var _currentFilename = null;

  function _findSpinRunForFile(filename) {
    if (!filename || !_allRuns.length) return null;
    var base = filename.toLowerCase().replace(/\.(sol|rs|pml)$/, "");
    // Exact filename match first, then stem match
    return _allRuns.find(function (r) {
      return r.is_spin && (
        r.filename.toLowerCase() === filename.toLowerCase() ||
        r.filename.toLowerCase().replace(/\.(sol|rs|pml)$/, "") === base
      );
    }) || null;
  }

  function _updateSpinBanner(tool, filename) {
    _currentTool = tool;
    _currentFilename = filename;

    var banner = document.getElementById("spin-switch-banner");
    var hdrBtn = document.getElementById("spin-switch-btn-hdr");
    if (!banner) return;

    var isSpinRun = (tool || "").toUpperCase() === "SPIN";
    if (isSpinRun) {
      banner.hidden = true;
      banner.style.display = "none";
      if (hdrBtn) { hdrBtn.hidden = true; hdrBtn.style.display = "none"; }
      return;
    }

    var spinRun = _findSpinRunForFile(filename);
    if (!spinRun) {
      banner.hidden = true;
      banner.style.display = "none";
      if (hdrBtn) { hdrBtn.hidden = true; hdrBtn.style.display = "none"; }
      return;
    }

    // Show banner + header button
    banner.hidden = false;
    banner.style.display = "flex";
    if (hdrBtn) { hdrBtn.hidden = false; hdrBtn.style.display = ""; }

    function switchToSpin() {
      window.DG_AUDIT_ID = String(spinRun.id);
      history.pushState({}, "", "/counterexample/" + spinRun.id);
      // Update selector
      var sel = document.getElementById("run-selector");
      if (sel) sel.value = String(spinRun.id);
      loadData(String(spinRun.id));
    }

    var bannerBtn = document.getElementById("spin-switch-btn");
    if (bannerBtn) {
      bannerBtn.onclick = null;
      bannerBtn.addEventListener("click", switchToSpin);
    }
    if (hdrBtn) {
      hdrBtn.onclick = null;
      hdrBtn.addEventListener("click", switchToSpin);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    const auditId = window.DG_AUDIT_ID || "latest";
    setupSearch();
    setupHexToggle();
    loadData(auditId);

    window._ceLoadData = loadData;

    // ── Run selector ────────────────────────────────────────────────────
    var selector = document.getElementById("run-selector");

    function populateRunSelector(currentId) {
      fetch("/api/v1/counterexample/runs", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (runs) {
          if (!runs || !runs.length) return;
          _allRuns = runs;

          // Group by filename for optgroups
          var byFile = {};
          runs.forEach(function (run) {
            var f = run.filename || "unknown";
            if (!byFile[f]) byFile[f] = [];
            byFile[f].push(run);
          });

          // Clear existing options except "Latest run"
          while (selector.options.length > 1) selector.remove(1);

          Object.keys(byFile).sort().forEach(function (filename) {
            var grp = document.createElement("optgroup");
            grp.label = filename;
            byFile[filename].forEach(function (run) {
              var opt = document.createElement("option");
              opt.value = run.id;
              var statusIcon = run.status === "PASS" ? "✓" : "✗";
              // Mark SPIN runs clearly
              var spinMark = run.is_spin ? " ⚛" : "";
              opt.textContent = run.tool + spinMark + "  " + statusIcon + "  " + (run.date || "").slice(0, 16);
              opt.style.color = run.status === "PASS" ? "var(--success)" : "var(--danger)";
              if (String(run.id) === String(currentId)) opt.selected = true;
              grp.appendChild(opt);
            });
            selector.appendChild(grp);
          });

          // After loading all runs, re-evaluate banner for current view
          if (_currentTool && _currentFilename) {
            _updateSpinBanner(_currentTool, _currentFilename);
          }
        })
        .catch(function () {});
    }

    setTimeout(function () {
      populateRunSelector(window.DG_AUDIT_ID);
    }, 200);

    if (selector) {
      selector.addEventListener("change", function () {
        var val = selector.value;
        window.DG_AUDIT_ID = val;
        var newUrl = val === "latest"
          ? "/counterexample/latest"
          : "/counterexample/" + val;
        history.pushState({}, "", newUrl);
        if (typeof window._ceLoadData === "function") {
          window._ceLoadData(val);
        }
      });
    }

    // ── Panel tab switching ──────────────────────────────────────────────
    document.querySelectorAll(".panel-tab").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var target = btn.getAttribute("data-tab");
        document.querySelectorAll(".panel-tab").forEach(function (b) {
          b.classList.remove("active"); b.setAttribute("aria-selected", "false");
        });
        document.querySelectorAll(".tab-content").forEach(function (c) {
          c.classList.remove("active"); c.hidden = true;
        });
        btn.classList.add("active"); btn.setAttribute("aria-selected", "true");
        var content = document.getElementById("tab-content-" + target);
        if (content) { content.classList.add("active"); content.hidden = false; }
      });
    });

    // ── Share button ─────────────────────────────────────────────────────
    var shareBtn = document.getElementById("share-btn");
    if (shareBtn) {
      shareBtn.addEventListener("click", function () {
        navigator.clipboard.writeText(window.location.href).then(function () {
          if (window.DGSocket) window.DGSocket.showToast("Copied", "Link copied to clipboard", "success");
        });
      });
    }

    // ── Re-populate selector after new verification ──────────────────────
    document.addEventListener("dg:verification_complete", function () {
      populateRunSelector(window.DG_AUDIT_ID);
      if (window.DG_AUDIT_ID === "latest") {
        setTimeout(function () { loadData("latest"); }, 1000);
      }
    });

    document.addEventListener("dg:state_update", function () {
      if (window.DG_AUDIT_ID === "latest") { loadData("latest"); }
    });
  });

  // Expose for _updateHeader to call after data loads
  window._ceUpdateSpinBanner = _updateSpinBanner;
})();
