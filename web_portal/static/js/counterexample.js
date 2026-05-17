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
        '<div class="empty-state-desc">The verification may have passed or failed without generating a trail.</div>' +
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
          (step.line ? '<span style="color:var(--text2);font-size:0.75rem;margin-right:0.4rem;">L' + step.line + '</span>' : '') +
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
        }
      });
    });
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

    panel.innerHTML = names
      .map(function (name) {
        const beforeVal = before[name];
        const afterVal = after[name];
        const changed = beforeVal !== undefined && beforeVal !== afterVal;
        const formattedBefore = formatValue(beforeVal);
        const formattedAfter = formatValue(afterVal);

        return (
          '<div class="var-row">' +
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
      })
      .join("");

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
          window.location.href = '/api/artifact/' + data.job_id + '/' + trailName;
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
  }

  function _updateStats(data) {
    function set(id, v) {
      const el = document.getElementById(id);
      if (el) el.textContent = (v !== undefined && v !== null) ? v : "—";
    }

    if (data.stats) {
      set("ce-stat-states", data.stats.states);
      set("ce-stat-trans",  data.stats.transitions);
      set("ce-stat-depth",  data.stats.depth);
    }

    if (data.ltl_properties) {
      set("ce-stat-rules", data.ltl_properties.length);
      const violations = data.ltl_properties.filter(function (r) {
        return r.status === "VIOLATED";
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
        ? "/api/counterexample/latest"
        : "/api/counterexample/" + encodeURIComponent(auditId);

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

  document.addEventListener("DOMContentLoaded", function () {
    const auditId = window.DG_AUDIT_ID || "latest";
    setupSearch();
    setupHexToggle();
    loadData(auditId);

    window._ceLoadData = loadData;

    document.addEventListener("dg:verification_complete", function () {
      if (window.DG_AUDIT_ID === "latest") {
        setTimeout(function () {
          loadData("latest");
        }, 1000);
      }
    });

    document.addEventListener("dg:state_update", function () {
      if (window.DG_AUDIT_ID === "latest") {
        loadData("latest");
      }
    });
  });
})();
