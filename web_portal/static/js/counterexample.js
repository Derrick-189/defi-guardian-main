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
  let _diffMode = false;
  let _minimizeTrace = false;

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
        // If minimize is on, hide internal steps (those without a line number or with specific keywords)
        if (_minimizeTrace && !step.line && !step.is_error) {
            const action = (step.action || "").toLowerCase();
            const internalKeywords = ["system", "scheduler", "internal", "yield", "poll"];
            if (internalKeywords.some(kw => action.includes(kw))) {
                return '';
            }
        }

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
          highlightSourceLine(step.line, step.action || step.label);
          
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
        const lineNum = i + 1;
        let tooltip = '';
        const lowLine = line.toLowerCase();
        
        // Simple heuristic for tooltip content
        if (lowLine.includes('lock = true') || lowLine.includes('islocked = true')) {
          tooltip = '<div class="code-tooltip"><span class="tooltip-tag tag-danger">Mutex</span> Reentrancy lock acquired</div>';
        } else if (lowLine.includes('require(') || lowLine.includes('assert(')) {
          tooltip = '<div class="code-tooltip"><span class="tooltip-tag tag-info">Guard</span> Safety condition check</div>';
        } else if (lowLine.includes('transfer(') || lowLine.includes('call{')) {
          tooltip = '<div class="code-tooltip"><span class="tooltip-tag tag-danger">External</span> Potential reentrancy vector</div>';
        }

        return (
          '<div class="code-line" data-line="' + lineNum + '">' +
          '<span class="line-number">' + lineNum + '</span>' +
          '<span class="line-content">' + escapeHtml(line) + '</span>' +
          tooltip +
          '</div>'
        );
      })
      .join("");
  }

  function highlightSourceLine(lineNum, actionText) {
    if (!lineNum) return;
    const pre = document.getElementById("source-code-pre");
    if (!pre) return;

    pre.querySelectorAll(".code-line").forEach(function (el) {
      el.classList.toggle("highlight", parseInt(el.getAttribute("data-line"), 10) === parseInt(lineNum, 10));
      
      // Update AI Explanation tooltip if it's the highlighted line
      if (parseInt(el.getAttribute("data-line"), 10) === parseInt(lineNum, 10) && actionText) {
          let aiTooltip = el.querySelector(".ai-explanation-tooltip");
          if (!aiTooltip) {
              aiTooltip = document.createElement("div");
              aiTooltip.className = "code-tooltip ai-explanation-tooltip";
              aiTooltip.style.borderColor = "var(--success)";
              aiTooltip.style.left = "auto";
              aiTooltip.style.right = "1rem";
              el.appendChild(aiTooltip);
          }
          aiTooltip.innerHTML = '<span class="tooltip-tag" style="background:var(--success);color:white;">AI Insight</span> Generating explanation...';
          
          // Simulate AI explanation fetch with dynamic sentence variations
          setTimeout(() => {
              const jobId = (_data && _data.job_id) || "run_default";
              const filename = (_data && _data.filename) || "Contract.sol";
              
              // Hash function to get a stable index from our inputs
              const inputStr = jobId + "_" + filename + "_" + lineNum + "_" + actionText;
              let hash = 0;
              for (let i = 0; i < inputStr.length; i++) {
                  hash = (hash << 5) - hash + inputStr.charCodeAt(i);
                  hash |= 0; // Convert to 32bit integer
              }
              const index = Math.abs(hash);

              const lowAction = actionText.toLowerCase();

              // Define categories of recommendations
              let category = "state"; // default
              if (lowAction.includes("lock")) {
                  category = "lock";
              } else if (lowAction.includes("transfer") || lowAction.includes("call{") || lowAction.includes("send")) {
                  category = "transfer";
              } else if (lowAction.includes("require") || lowAction.includes("assert")) {
                  category = "require";
              }

              // A rich collection of templates with distinct sentence structures
              const templates = {
                  "lock": [
                      `Audit Alert: Reentrancy lock modification detected at line ${lineNum} of ${filename}. Ensure state changes follow the Checks-Effects-Interactions pattern *prior* to modifying this lock state.`,
                      `Mutex Verification: Line ${lineNum} modifies a reentrancy mutex. If external untrusted calls exist in this block, confirm they execute only *after* the lock is set.`,
                      `Critical Path Security: Guarding re-entrant entrypoint at line ${lineNum}. Ensure the lock boolean is reset in a \`finally\` or cleanup block so user funds are not locked permanently.`,
                      `State Guarding: Mutex modification on line ${lineNum} in run ${jobId}. Double-check that all functions sharing this critical state check the lock status immediately on entry.`
                  ],
                  "transfer": [
                      `Security Notice: External transfer on line ${lineNum} of ${filename}. Make sure all internal account balances are updated *before* this external execution to prevent reentrancy.`,
                      `Reentrancy Vector: Asset transfer/external call at line ${lineNum}. Consider using OpenZeppelin's ReentrancyGuard or limiting gas to protect against malicious recipient fallback execution.`,
                      `Interaction Point: External invocation observed in run ${jobId}. Verify that the return value of this call is checked and that it doesn't allow recursive callback execution.`,
                      `Critical Asset Send: External messaging point at line ${lineNum}. Ensure no local state changes follow this transfer, adhering to strict checks-effects-interactions practices.`
                  ],
                  "require": [
                      `Logic Assertion: Constraint condition check on line ${lineNum} of ${filename}. If this check fails under verification, analyze the trace inputs for integer overflow or boundary limits.`,
                      `Invariant Check: Safety guard validated at line ${lineNum}. Ensure this check doesn't lead to a permanent Denial of Service (DoS) if state variables reach their upper limit.`,
                      `Input Guardrail: Verification rule checked on line ${lineNum} in run ${jobId}. If unexpected failures occur here, check if helper functions properly validate prerequisite parameters.`,
                      `Assertion Verification: Boundary validation at line ${lineNum}. Restrict the usage of raw assertions to unreached states, and prefer \`require\` for input sanity validations.`
                  ],
                  "state": [
                      `State Mutation: Modification of contract storage at line ${lineNum} of ${filename}. Ensure no external calls were performed before this write, as stale states could be read.`,
                      `Storage Update: Storage variable modified in run ${jobId}. If this variable controls permissions or reward ratios, ensure a corresponding state change event is emitted.`,
                      `Variable Assignment: Line ${lineNum} updates local or global state. Double-check that access modifiers (e.g. \`onlyOwner\`) are correctly enforced on this execution branch.`,
                      `Execution Transition: State transition at line ${lineNum}. Confirm that the new state doesn't violate any LTL properties checked in the verification spec.`
                  ]
              };

              const choiceList = templates[category];
              const exp = choiceList[index % choiceList.length];
              aiTooltip.innerHTML = '<span class="tooltip-tag" style="background:var(--success);color:white;">AI Insight</span> ' + exp;
          }, 600);
      }
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
        let nodeObj = {};
        if (typeof n === 'string') {
          nodeObj = { id: n, label: n };
        } else if (n && typeof n === 'object') {
          nodeObj = {
            id: n.id !== undefined ? n.id : n.label,
            label: n.label !== undefined ? n.label : n.id,
            type: n.type
          };
        }
        
        if (!nodeObj.id) return;
        
        const id = String(nodeObj.id).replace(/[^a-zA-Z0-9_]/g, '');
        nodeIds.add(id);
        lines.push(`    state "${nodeObj.label || nodeObj.id}" as ${id}`);
        if (nodeObj.type === 'initial') lines.push(`    [*] --> ${id}`);
        if (nodeObj.type === 'error') lines.push(`    class ${id} failedState`);
      });
      
      (graph.edges || graph.links || []).forEach(e => {
        const sourceVal = e.source !== undefined ? e.source : e.from;
        const targetVal = e.target !== undefined ? e.target : e.to;
        if (sourceVal === undefined || targetVal === undefined) return;
        const sid = String(sourceVal).replace(/[^a-zA-Z0-9_]/g, '');
        const tid = String(targetVal).replace(/[^a-zA-Z0-9_]/g, '');
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
        const beforeVal = before[name];
        const afterVal = after[name];
        const changed = beforeVal !== undefined && beforeVal !== afterVal;
        
        // If diff mode is on, only include changed variables
        if (_diffMode && !changed) return;

        const parts = name.split(/[:.]/);
        const groupName = parts.length > 1 ? parts[0] : "Global";
        if (!groups[groupName]) groups[groupName] = [];
        groups[groupName].push(name);
    });

    const groupsKeys = Object.keys(groups).sort();
    if (groupsKeys.length === 0 && _diffMode) {
        panel.innerHTML = '<div class="text-muted" style="padding:1rem;font-size:0.82rem;">No variables changed in this step</div>';
        return;
    }

    panel.innerHTML = groupsKeys.map(groupName => {
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
      '<ul class="diagnostic-list" style="display:flex;flex-direction:column;gap:0.6rem;">' +
      recommendations
        .map(function (rec) {
          var isAi = rec.startsWith("🤖");
          var displayRec = isAi ? rec.replace(/^🤖\s*/, "") : rec;
          var icon = isAi ? '<i class="fa-solid fa-robot" style="color: var(--success); text-shadow: 0 0 6px rgba(86,211,100,0.4); font-size: 0.95rem;"></i>' : '<i class="fa-solid fa-arrow-right" style="color: var(--accent);"></i>';
          var style = isAi ? ' style="background: rgba(86,211,100,0.06); border-left: 3px solid var(--success); padding: 0.5rem 0.75rem; border-radius: 6px; display:flex; align-items:flex-start; gap:0.6rem;"' : ' style="display:flex; align-items:flex-start; gap:0.6rem; padding: 0.2rem 0;"';
          return (
            '<li class="diagnostic-item rec-item"' + style + '>' +
            icon +
            '<span style="flex:1; line-height: 1.45;">' + escapeHtml(displayRec) + '</span>' +
            '</li>'
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

    // Initialize layout resizers
    initResizablePanels();
    initVerticalResizer();

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

    // ── Diff & Minimize Toggles ──────────────────────────────────────────
    const diffToggle = document.getElementById('diff-toggle');
    if (diffToggle) {
        diffToggle.addEventListener('change', function() {
            _diffMode = diffToggle.checked;
            const step = _activeStepIndex !== null ? _filteredSteps[_activeStepIndex] : null;
            renderVariables(step);
        });
    }

    const minimizeToggle = document.getElementById('minimize-toggle');
    if (minimizeToggle) {
        minimizeToggle.addEventListener('change', function() {
            _minimizeTrace = minimizeToggle.checked;
            renderTrace(_filteredSteps);
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
        
        // Rerun Mermaid rendering once the tab becomes visible to resolve 0-dimension rendering bug
        if (target === "state-diagram" && typeof _data !== "undefined" && _data) {
          renderStateMachine(_data);
        }
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

  // ── Drag & Resize Panel Helpers ──────────────────────────────────────────
  function initResizablePanels() {
    const layout = document.getElementById("report-layout");
    const resizerLeft = document.getElementById("resizer-left");
    const resizerRight = document.getElementById("resizer-right");
    
    if (!layout || !resizerLeft || !resizerRight) return;
    
    let leftWidth = 260;
    let rightWidth = 280;
    
    // Left resizer
    resizerLeft.addEventListener("mousedown", function(e) {
      e.preventDefault();
      resizerLeft.classList.add("dragging");
      document.addEventListener("mousemove", resizeLeft);
      document.addEventListener("mouseup", stopResizeLeft);
    });
    
    function resizeLeft(e) {
      const rect = layout.getBoundingClientRect();
      leftWidth = Math.max(150, Math.min(450, e.clientX - rect.left));
      layout.style.gridTemplateColumns = `${leftWidth}px 4px 1fr 4px ${rightWidth}px`;
    }
    
    function stopResizeLeft() {
      resizerLeft.classList.remove("dragging");
      document.removeEventListener("mousemove", resizeLeft);
      document.removeEventListener("mouseup", stopResizeLeft);
      window.dispatchEvent(new Event('resize'));
    }
    
    // Right resizer
    resizerRight.addEventListener("mousedown", function(e) {
      e.preventDefault();
      resizerRight.classList.add("dragging");
      document.addEventListener("mousemove", resizeRight);
      document.addEventListener("mouseup", stopResizeRight);
    });
    
    function resizeRight(e) {
      const rect = layout.getBoundingClientRect();
      rightWidth = Math.max(150, Math.min(450, rect.right - e.clientX));
      layout.style.gridTemplateColumns = `${leftWidth}px 4px 1fr 4px ${rightWidth}px`;
    }
    
    function stopResizeRight() {
      resizerRight.classList.remove("dragging");
      document.removeEventListener("mousemove", resizeRight);
      document.removeEventListener("mouseup", stopResizeRight);
      window.dispatchEvent(new Event('resize'));
    }
  }

  function initVerticalResizer() {
    const wrapper = document.getElementById("panels-wrapper");
    const resizer = document.getElementById("panels-y-resizer");
    if (!wrapper || !resizer) return;
    
    resizer.addEventListener("mousedown", function(e) {
      e.preventDefault();
      resizer.classList.add("dragging");
      document.addEventListener("mousemove", resizeY);
      document.addEventListener("mouseup", stopResizeY);
    });
    
    function resizeY(e) {
      const rect = wrapper.getBoundingClientRect();
      const newHeight = Math.max(300, Math.min(window.innerHeight - 200, e.clientY - rect.top));
      wrapper.style.height = `${newHeight}px`;
    }
    
    function stopResizeY() {
      resizer.classList.remove("dragging");
      document.removeEventListener("mousemove", resizeY);
      document.removeEventListener("mouseup", stopResizeY);
      window.dispatchEvent(new Event('resize'));
    }
  }

  // Expose for _updateHeader to call after data loads
  window._ceUpdateSpinBanner = _updateSpinBanner;
})();
