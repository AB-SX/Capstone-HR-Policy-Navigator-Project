(() => {
  const D = window.TRACE_DATA || { runs: [], traces: [] };
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const REQUIRED = ["retrieval_miss", "reasoning_error", "tool_call_error", "hallucination"];
  const OTHER = ["skipped_search", "over_refusal", "under_refusal"];
  const LABEL = { retrieval_miss: "Retrieval miss", reasoning_error: "Reasoning error", tool_call_error: "Tool-call error",
    hallucination: "Hallucination", skipped_search: "Skipped search", over_refusal: "Over-refusal", under_refusal: "Under-refusal" };
  const charts = {};
  let run = null, sortK = "id", sortDir = 1;

  const pct = (a, b) => (b ? (100 * a / b) : 0);
  const fmt1 = (x) => (Math.round(x * 10) / 10).toFixed(1);
  const quant = (xs, q) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.floor(s.length * q))] : 0; };
  const dur = (ms) => ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;
  const mean = (xs) => xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
  const tokens = (r) => (r.prompt_tokens || 0) + (r.completion_tokens || 0);
  const judgePill = (j) => j === "correct" ? `<span class="pill p-ok">correct</span>` : j === "partially_correct" ? `<span class="pill p-warn">partial</span>` : `<span class="pill p-bad">${esc(j || "incorrect")}</span>`;
  const failPill = (f) => f ? `<span class="pill ${REQUIRED.includes(f) ? "p-bad" : "p-info"}">${esc(LABEL[f] || f)}</span>` : `<span class="pill p-mute">none</span>`;

  // ---------------- setup
  const sel = $("#runSel");
  const order = [...D.runs].sort((a, b) => (b.system === "m2") - (a.system === "m2") || b.run - a.run);
  order.forEach((r) => sel.insertAdjacentHTML("beforeend", `<option value="${r.run_id}">${esc(r.label)}</option>`));
  $("#modelBadge").textContent = `${D.model || "model"} · ${D.runs.reduce((a, r) => a + r.rows.length, 0)} executions`;
  $("#spanCount").textContent = (D.traces || []).length;
  const fFail = $("#fFail");
  [...REQUIRED, ...OTHER].forEach((f) => fFail.insertAdjacentHTML("beforeend", `<option value="${f}">${LABEL[f]}</option>`));
  fFail.insertAdjacentHTML("beforeend", `<option value="__none">No failure</option>`);

  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => { x.classList.toggle("active", x === t); x.setAttribute("aria-selected", x === t); });
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + t.dataset.view));
  }));
  sel.addEventListener("change", () => select(sel.value));
  ["#q", "#fJudge", "#fFail", "#fDiff"].forEach((s) => $(s).addEventListener("input", renderTable));
  document.querySelectorAll("#tbl th").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.k; sortDir = sortK === k ? -sortDir : 1; sortK = k; renderTable();
  }));

  // ---------------- overview
  function kpis(rows) {
    const n = rows.length;
    const ok = rows.filter((r) => r.judge === "correct").length;
    const comp = rows.filter((r) => !["error", "step_cap"].includes(r.status)).length;
    const lat = rows.map((r) => +r.latency_s || 0);
    const items = [
      ["Executions", n, `${run.label.split(" · ")[0]} on Qwen3-8B`],
      ["Accuracy", fmt1(pct(ok, n)) + "%", `${ok} judged correct`],
      ["Task completion", fmt1(pct(comp, n)) + "%", "No error or step cap"],
      ["Tool calls / task", mean(rows.map((r) => r.tool_calls || 0)).toFixed(2), `${mean(rows.map((r) => r.llm_calls || 0)).toFixed(2)} LLM calls`],
      ["Latency p50 / p95", `${fmt1(quant(lat, .5))} / ${fmt1(quant(lat, .95))}s`, "End to end"],
      ["Tokens / query", Math.round(mean(rows.map(tokens))).toLocaleString(), `${Math.round(mean(rows.map((r) => r.completion_tokens || 0)))} output`],
    ];
    $("#kpis").innerHTML = items.map(([l, v, s]) => `<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${esc(s)}</div></div>`).join("");
  }

  function chart(id, cfg) { if (charts[id]) charts[id].destroy(); charts[id] = new Chart(document.getElementById(id), cfg); }
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily; Chart.defaults.color = "#5e6763";
  const grid = { color: "#efede7" };

  function overview(rows) {
    kpis(rows);
    const fails = [...REQUIRED, ...OTHER];
    chart("chFail", { type: "bar", data: { labels: fails.map((f) => LABEL[f]),
      datasets: [{ data: fails.map((f) => rows.filter((r) => r.failure === f).length),
        backgroundColor: fails.map((f) => REQUIRED.includes(f) ? "#b23a2e" : "#3b5ba5"), borderRadius: 4 }] },
      options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false } },
        scales: { x: { grid, ticks: { precision: 0 } }, y: { grid: { display: false } } } } });

    const bins = [0, 5, 10, 15, 20, 30, 45, 60, Infinity];
    const lab = bins.slice(0, -1).map((b, i) => bins[i + 1] === Infinity ? `${b}s+` : `${b}–${bins[i + 1]}s`);
    chart("chLat", { type: "bar", data: { labels: lab, datasets: [{ data: lab.map((_, i) => rows.filter((r) => r.latency_s >= bins[i] && r.latency_s < bins[i + 1]).length), backgroundColor: "#0f6e64", borderRadius: 4 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { grid, ticks: { precision: 0 } }, x: { grid: { display: false } } } } });

    const diffs = ["easy", "medium", "hard"];
    const by = (d, j) => rows.filter((r) => r.difficulty === d && (j ? r.judge === j : !["correct", "partially_correct"].includes(r.judge))).length;
    chart("chDiff", { type: "bar", data: { labels: diffs.map((d) => `${d} (${rows.filter((r) => r.difficulty === d).length})`), datasets: [
      { label: "Correct", data: diffs.map((d) => by(d, "correct")), backgroundColor: "#2f7d4f", borderRadius: 3 },
      { label: "Partial", data: diffs.map((d) => by(d, "partially_correct")), backgroundColor: "#d9a441", borderRadius: 3 },
      { label: "Incorrect", data: diffs.map((d) => by(d, null)), backgroundColor: "#b23a2e", borderRadius: 3 }] },
      options: { maintainAspectRatio: false, scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, grid, ticks: { precision: 0 } } },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } } } } });

    const pt = (j) => rows.filter((r) => (j === "correct" ? r.judge === "correct" : r.judge !== "correct")).map((r) => ({ x: tokens(r), y: r.latency_s, id: r.id }));
    chart("chTok", { type: "scatter", data: { datasets: [
      { label: "Correct", data: pt("correct"), backgroundColor: "rgba(47,125,79,.6)", pointRadius: 4 },
      { label: "Not correct", data: pt("other"), backgroundColor: "rgba(178,58,46,.65)", pointRadius: 4 }] },
      options: { maintainAspectRatio: false, onClick: (e, els) => { if (els[0]) { const d = charts.chTok.data.datasets[els[0].datasetIndex].data[els[0].index]; openRow(rows.find((r) => r.id === d.id)); } },
        scales: { x: { title: { display: true, text: "Tokens (in + out)" }, grid }, y: { title: { display: true, text: "Latency (s)" }, grid } },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } }, tooltip: { callbacks: { label: (c) => `Q${c.raw.id}: ${c.raw.x} tok, ${c.raw.y}s` } } } } });

    const tc = {};
    rows.forEach((r) => (r.tools_used || []).forEach((t) => (tc[t] = (tc[t] || 0) + 1)));
    const errs = rows.reduce((a, r) => a + (r.tool_errors || 0), 0);
    const max = Math.max(1, ...Object.values(tc));
    $("#toolBars").innerHTML = (Object.keys(tc).length ? Object.entries(tc).sort((a, b) => b[1] - a[1]) : [["(no tool calls)", 0]])
      .map(([t, n]) => `<div class="tb"><code>${esc(t)}</code><div class="bar"><i style="width:${100 * n / max}%"></i></div><span class="n">${n}</span></div>`).join("")
      + `<div class="tb"><span>Tool errors</span><div class="bar"><i style="width:${100 * errs / max}%;background:#b23a2e"></i></div><span class="n">${errs}</span></div>`;
    $("#foot").textContent = `Source: data/evaluation/results/archive/${run.run_id}_rows.jsonl · committed ${run.committed ? new Date(run.committed).toLocaleString() : "n/a"} · dashboard built ${new Date(D.built).toLocaleString()}`;
  }

  // ---------------- executions table
  function renderTable() {
    const q = $("#q").value.toLowerCase(), fj = $("#fJudge").value, ff = $("#fFail").value, fd = $("#fDiff").value;
    let rows = run.rows.filter((r) => (!q || r.query.toLowerCase().includes(q)) && (!fj || r.judge === fj)
      && (!ff || (ff === "__none" ? !r.failure : r.failure === ff)) && (!fd || r.difficulty === fd));
    const key = (r) => sortK === "tokens" ? tokens(r) : r[sortK] ?? "";
    rows.sort((a, b) => (key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0) * sortDir);
    $("#shown").textContent = `${rows.length} of ${run.rows.length}`;
    $("#tbl tbody").innerHTML = rows.map((r) => `<tr data-id="${r.id}" tabindex="0">
      <td class="num">${r.id}</td><td class="q">${esc(r.query)}</td><td>${judgePill(r.judge)}</td><td>${failPill(r.failure)}</td>
      <td><span class="pill p-mute">${esc(r.status)}</span></td><td class="num">${r.tool_calls ?? 0}</td><td class="num">${r.llm_calls ?? 0}</td>
      <td class="num">${tokens(r).toLocaleString()}</td><td class="num">${fmt1(+r.latency_s || 0)}s</td></tr>`).join("");
    document.querySelectorAll("#tbl tbody tr").forEach((tr) => {
      const go = () => openRow(run.rows.find((r) => String(r.id) === tr.dataset.id));
      tr.addEventListener("click", go); tr.addEventListener("keydown", (e) => e.key === "Enter" && go());
    });
  }

  // ---------------- drawer
  const drawer = $("#drawer"), bg = $("#drawerBg");
  function closeDrawer() { drawer.hidden = true; bg.hidden = true; drawer.setAttribute("aria-hidden", "true"); }
  $("#dClose").addEventListener("click", closeDrawer); bg.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => e.key === "Escape" && closeDrawer());

  function openRow(r) {
    if (!r) return;
    const steps = (r.tools_used || []);
    const flow = run.system === "m2"
      ? ["guard_in", "router", ...(r.route === "policy" ? ["planner", ...steps.map((s) => "tool:" + s), ...(r.critic_rounds ? ["critic"] : []), "responder"] : [r.route]), "finalize"]
      : ["agent", ...steps.map((s) => "tool:" + s), "answer"];
    const tr = (D.traces || []).find((t) => t.system === run.system && String(t.meta?.question_id) === String(r.id));
    $("#dTitle").textContent = `Q${r.id} · ${run.label}`;
    $("#dBody").innerHTML = `
      <div class="sec"><h3>Question</h3><div class="box">${esc(r.query)}</div></div>
      <div class="sec metrics">
        <div><b>${fmt1(+r.latency_s || 0)}s</b><span>Latency</span></div><div><b>${r.llm_calls ?? 0}</b><span>LLM calls</span></div>
        <div><b>${r.tool_calls ?? 0}</b><span>Tool calls</span></div><div><b>${tokens(r).toLocaleString()}</b><span>Tokens</span></div>
      </div>
      <div class="sec"><h3>Execution path</h3><div class="steps">${flow.map((s) => `<span class="step">${esc(s)}</span>`).join('<span class="arrow">→</span>')}</div>
        <p class="hint" style="margin:6px 0 0">${tr ? "Span trace available below." : "Reconstructed from the saved run record (route, tools, critic rounds). Capture a span trace for exact timings."}</p></div>
      <div class="sec"><h3>Verdict</h3>${judgePill(r.judge)} ${failPill(r.failure)} <span class="pill p-mute">${esc(r.status)}</span>
        <div class="box" style="margin-top:8px">${esc(r.judge_reason || "")}</div></div>
      <div class="sec"><h3>Model answer</h3><div class="box">${esc(r.answer)}</div></div>
      <div class="sec"><h3>Gold answer</h3><div class="box">${esc(r.gold_answer)}</div></div>
      <div class="sec"><h3>Grounding checks</h3><div class="steps">
        <span class="pill ${r.gold_retrieved ? "p-ok" : "p-bad"}">gold doc retrieved: ${r.gold_retrieved}</span>
        <span class="pill ${r.cited_gold ? "p-ok" : "p-warn"}">cited gold: ${r.cited_gold}</span>
        <span class="pill ${r.has_citation ? "p-ok" : "p-warn"}">has citation: ${r.has_citation}</span>
        <span class="pill ${(r.ungrounded_numbers || []).length ? "p-bad" : "p-ok"}">ungrounded numbers: ${(r.ungrounded_numbers || []).length}</span>
        <span class="pill ${r.json_repairs ? "p-warn" : "p-ok"}">JSON repairs: ${r.json_repairs ?? 0}</span>
        <span class="pill ${r.tool_errors ? "p-bad" : "p-ok"}">tool errors: ${r.tool_errors ?? 0}</span></div></div>
      <div class="sec"><h3>Metadata</h3><div class="box">difficulty: ${esc(r.difficulty)} · type: ${esc(r.type)} · topic: ${esc(r.topic)}\nprompt tokens: ${r.prompt_tokens} · completion tokens: ${r.completion_tokens} · critic rounds: ${r.critic_rounds ?? "n/a"}${r.error ? "\nerror: " + esc(r.error) : ""}</div></div>
      ${tr ? `<div class="sec"><h3>Span trace</h3><div id="dWf"></div></div>` : ""}`;
    if (tr) waterfall(tr, document.getElementById("dWf"), null);
    drawer.hidden = false; bg.hidden = false; drawer.setAttribute("aria-hidden", "false"); $("#dClose").focus();
  }

  // ---------------- span traces
  function depthOf(spans) {
    const by = Object.fromEntries(spans.map((s) => [s.span_id, s])); const memo = {};
    const d = (s) => memo[s.span_id] ??= (s.parent_id && by[s.parent_id] ? d(by[s.parent_id]) + 1 : 0);
    spans.forEach(d); return memo;
  }
  function waterfall(t, el, detailEl) {
    const spans = [...t.spans].sort((a, b) => a.start_ms - b.start_ms); const dep = depthOf(spans);
    const total = Math.max(1, t.duration_ms || Math.max(...spans.map((s) => s.end_ms || 0)));
    el.innerHTML = `<div class="legend"><span><i class="k-node"></i>graph node</span><span><i class="k-llm"></i>model call</span><span><i class="k-tool"></i>tool call</span><span><i class="k-err"></i>error</span></div>` +
      spans.map((s, i) => `<div class="wf-row" data-i="${i}" tabindex="0"><div class="wf-name" style="padding-left:${dep[s.span_id] * 14}px" title="${esc(s.name)}">${esc(s.name)}</div>
        <div class="wf-track"><span class="wf-bar ${s.ok ? "k-" + s.kind : "k-err"}" style="left:${100 * s.start_ms / total}%;width:${Math.max(.4, 100 * (s.dur_ms || 0) / total)}%"></span></div>
        <div class="wf-dur">${dur(s.dur_ms || 0)}</div></div>`).join("");
    const show = (i) => {
      el.querySelectorAll(".wf-row").forEach((r) => r.classList.toggle("sel", r.dataset.i == i));
      const s = spans[i]; const tgt = detailEl || el;
      const html = `<div class="sec"><h3>${esc(s.name)} · ${esc(s.kind)}</h3>
        <div class="steps"><span class="pill ${s.ok ? "p-ok" : "p-bad"}">${s.ok ? "ok" : "error"}</span><span class="pill p-mute">${dur(s.dur_ms || 0)}</span>
        ${Object.entries(s.attrs || {}).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => `<span class="pill p-info">${esc(k)}: ${esc(v)}</span>`).join("")}</div>
        ${s.error ? `<pre>${esc(s.error)}</pre>` : ""}${s.input ? `<h3 style="margin-top:10px">Input</h3><pre>${esc(s.input)}</pre>` : ""}${s.output ? `<h3>Output</h3><pre>${esc(s.output)}</pre>` : ""}</div>`;
      if (detailEl) detailEl.innerHTML = html; else { let d = el.querySelector(".inl"); if (!d) { d = document.createElement("div"); d.className = "inl spandetail"; el.appendChild(d); } d.innerHTML = html; }
    };
    el.querySelectorAll(".wf-row").forEach((r) => { r.addEventListener("click", () => show(+r.dataset.i)); r.addEventListener("keydown", (e) => e.key === "Enter" && show(+r.dataset.i)); });
  }
  function spansView() {
    const T = D.traces || [];
    $("#spanEmpty").hidden = !!T.length; $("#spanWrap").hidden = !T.length;
    if (!T.length) return;
    const list = $("#traceList");
    list.innerHTML = T.map((t, i) => { const ev = t.result?.eval || {}; return `<div class="ti" data-i="${i}" tabindex="0"><div class="t">${esc(t.question)}</div>
      <div class="m"><span>${esc(t.system.toUpperCase())} Q${esc(t.meta?.question_id)}</span><span>${(t.duration_ms / 1000).toFixed(1)}s</span><span>${t.spans.length} spans</span><span>${esc(ev.judge || t.result?.status || "")}</span></div></div>`; }).join("");
    const pick = (i) => {
      list.querySelectorAll(".ti").forEach((x) => x.classList.toggle("active", x.dataset.i == i));
      const t = T[i], u = t.result?.usage || {}, ev = t.result?.eval || {};
      $("#wfTitle").textContent = `${t.system.toUpperCase()} · Q${t.meta?.question_id ?? ""}`;
      $("#wfMeta").textContent = `${t.started_at} · ${(t.duration_ms / 1000).toFixed(2)}s · ${u.llm_calls ?? "?"} LLM calls · ${(u.prompt_tokens || 0) + (u.completion_tokens || 0)} tokens · ${ev.judge || t.result?.status}`;
      waterfall(t, $("#waterfall"), $("#spanDetail"));
      $("#spanDetail").innerHTML = `<div class="sec"><h3>Question</h3><div class="box">${esc(t.question)}</div></div><div class="sec"><h3>Answer</h3><div class="box">${esc(t.result?.answer)}</div></div>${ev.judge_reason ? `<div class="sec"><h3>Judge</h3><div class="box">${esc(ev.judge)}: ${esc(ev.judge_reason)}</div></div>` : ""}<p class="hint">Click a span for its inputs, outputs and token counts.</p>`;
    };
    list.querySelectorAll(".ti").forEach((x) => { x.addEventListener("click", () => pick(+x.dataset.i)); x.addEventListener("keydown", (e) => e.key === "Enter" && pick(+x.dataset.i)); });
    pick(0);
  }

  // ---------------- compare
  function compare() {
    const m = (r) => { const R = r.rows, n = R.length, lat = R.map((x) => +x.latency_s || 0);
      return { n, acc: pct(R.filter((x) => x.judge === "correct").length, n), part: pct(R.filter((x) => ["correct", "partially_correct"].includes(x.judge)).length, n),
        hard: pct(R.filter((x) => x.difficulty === "hard" && x.judge === "correct").length, R.filter((x) => x.difficulty === "hard").length),
        tools: mean(R.map((x) => x.tool_calls || 0)), llm: mean(R.map((x) => x.llm_calls || 0)), tok: mean(R.map(tokens)), p50: quant(lat, .5), p95: quant(lat, .95),
        fails: Object.fromEntries([...REQUIRED, ...OTHER].map((f) => [f, R.filter((x) => x.failure === f).length])) }; };
    const ms = order.map((r) => [r, m(r)]);
    const rowsDef = [["Accuracy", (x) => fmt1(x.acc) + "%"], ["Correct or partial", (x) => fmt1(x.part) + "%"], ["Hard questions correct", (x) => fmt1(x.hard) + "%"],
      ["Tool calls / task", (x) => x.tools.toFixed(2)], ["LLM calls / task", (x) => x.llm.toFixed(2)], ["Tokens / query", (x) => Math.round(x.tok).toLocaleString()],
      ["Latency p50", (x) => fmt1(x.p50) + "s"], ["Latency p95", (x) => fmt1(x.p95) + "s"], ...[...REQUIRED, ...OTHER].map((f) => [LABEL[f], (x) => x.fails[f]])];
    $("#cmp").innerHTML = `<thead><tr><th>Metric</th>${ms.map(([r]) => `<th class="num">${esc(r.label)}</th>`).join("")}</tr></thead><tbody>` +
      rowsDef.map(([l, f]) => `<tr><td>${l}</td>${ms.map(([, x]) => `<td class="num">${f(x)}</td>`).join("")}</tr>`).join("") + "</tbody>";
  }


  // ---------------- pipeline (Week 1 baseline -> retrieval -> agents)
  function pipeline() {
    const P = D.pipeline || {}; const W = P.week1 || []; const ids = new Set(P.overlap_ids || []);
    if (!W.length) { $("#plNote").textContent = "Week 1 results not found in this build."; return; }
    const SN = { baseline_direct: "Direct (zero-shot)", few_shot_structured: "Few-shot structured", chain_of_thought: "Chain-of-thought", decomposition: "Decomposition" };
    const strats = Object.keys(SN).filter((k) => W.some((r) => r.strategy === k));
    const w1 = Object.fromEntries(strats.map((k) => { const R = W.filter((r) => r.strategy === k);
      return [k, { n: R.length, orig: pct(R.filter((r) => r.orig_correct).length, R.length), det: pct(R.filter((r) => r.det_correct).length, R.length),
        f1: mean(R.map((r) => r.token_f1)), by: Object.fromEntries(R.map((r) => [r.id, r])) }]; }));
    const agentRuns = [...D.runs].sort((a, b) => a.system.localeCompare(b.system) || a.run - b.run).map((r) => {
      const R = r.rows.filter((x) => ids.has(+x.id));
      return { r, n: R.length, det: pct(R.filter((x) => x.det_correct).length, R.length), judge: pct(R.filter((x) => x.judge === "correct").length, R.length),
        gold: pct(R.filter((x) => x.gold_retrieved).length, R.length), by: Object.fromEntries(R.map((x) => [+x.id, x])) }; });
    const best = (a, k) => a.reduce((m, x) => (x[k] > m[k] ? x : m), a[0]);
    const w1arr = strats.map((k) => ({ k, ...w1[k] }));
    const bOrig = best(w1arr, "orig"), bDet = best(w1arr, "det");
    const latest = (sys) => agentRuns.filter((a) => a.r.system === sys).sort((a, b) => b.r.run - a.r.run)[0];
    const m1 = latest("m1"), m2 = latest("m2");
    const RV = P.retrieval, RP = P.retrieval_prod;
    const prodVar = RP?.variant || "c3", prodRr = RP?.reranker || "minilm-l6";
    const retRows = (RV?.results || []);
    const prodRow = retRows.find((r) => r.method === `hybrid+${prodRr}` && r.variant === prodVar);
    const bm25Row = retRows.find((r) => r.method === "bm25" && r.variant === prodVar);

    $("#plNote").innerHTML = `<b>How to read this.</b> Week 1 was run on the original ${ids.size}-question set, before any agent code. Those ${ids.size} questions are ids 1–${Math.max(...ids)} of the frozen eval_v2 set with identical gold answers, so every comparison on this tab is restricted to them.
      Week 1 has no LLM judge, so the like-for-like metric is the deterministic rule (token F1 ≥ 0.5, or recall ≥ 0.55 with every gold number present). Week 1 answers are re-scored here with the agents' scorer, which drops stopwords, so they come out lower than the notebook's own numbers. Both are shown. Retrieval recall is measured on its own, as the brief requires.`;

    const stage = (k, t, v, sub) => `<div class="stage"><div class="k">${k}</div><div class="t">${t}</div><div class="v">${v}</div><div class="s">${sub}</div></div>`;
    $("#plStages").innerHTML =
      stage("Week 1 · baseline", "Prompting only", fmt1(bDet.det) + "%", `Best strategy on the shared scorer (${SN[bDet.k]}). ${fmt1(bOrig.orig)}% on the notebook's scorer (${SN[bOrig.k]}).`) +
      stage("Week 2 · RAG", "Hybrid + reranker", prodRow ? fmt1(100 * prodRow["doc_R@5"]) + "%" : "n/a", prodRow ? `Gold document in the top 5 (${prodVar}, ${prodRr}). Recall@1 ${fmt1(100 * prodRow["doc_R@1"])}% vs ${fmt1(100 * bm25Row["doc_R@1"])}% for BM25 alone.` : "") +
      stage("Week 3 · M1", "Single agent + tools", fmt1(m1.det) + "%", `Run ${m1.r.run}, shared scorer. LLM judge: ${fmt1(m1.judge)}%.`) +
      stage("Week 3 · M2", "Planner → executor → critic", fmt1(m2.det) + "%", `Run ${m2.r.run}, shared scorer. LLM judge: ${fmt1(m2.judge)}%.`);

    $("#plAccHint").textContent = `${ids.size} shared questions · Qwen3-8B throughout`;
    const labels = [...strats.map((k) => "W1 · " + SN[k]), ...agentRuns.map((a) => `${a.r.system.toUpperCase()} · run ${a.r.run}`)];
    chart("chPipe", { type: "bar", data: { labels, datasets: [
      { label: "Deterministic rule (shared scorer)", data: [...strats.map((k) => w1[k].det), ...agentRuns.map((a) => a.det)], backgroundColor: "#0f6e64", borderRadius: 4 },
      { label: "Week 1 notebook scorer", data: [...strats.map((k) => w1[k].orig), ...agentRuns.map(() => null)], backgroundColor: "#9cc7c0", borderRadius: 4 },
      { label: "LLM judge", data: [...strats.map(() => null), ...agentRuns.map((a) => a.judge)], backgroundColor: "#3b5ba5", borderRadius: 4 }] },
      options: { maintainAspectRatio: false, scales: { y: { min: 0, max: 100, grid, ticks: { callback: (v) => v + "%" } }, x: { grid: { display: false } } },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } }, tooltip: { callbacks: { label: (c) => c.raw == null ? null : `${c.dataset.label}: ${fmt1(c.raw)}%` } } } } });

    $("#w1tbl").innerHTML = `<thead><tr><th>Strategy</th><th class="num">Notebook scorer</th><th class="num">Shared scorer</th><th class="num">Mean token F1</th></tr></thead><tbody>` +
      w1arr.map((x) => `<tr><td>${SN[x.k]}</td><td class="num">${fmt1(x.orig)}%</td><td class="num">${fmt1(x.det)}%</td><td class="num">${x.f1.toFixed(3)}</td></tr>`).join("") + "</tbody>";
    $("#w1note").textContent = `${W.length} real calls (${strats.length} strategies × ${ids.size} questions), committed ${P.week1_committed ? new Date(P.week1_committed).toLocaleDateString() : "n/a"}. Source: src/prompts/track_b_week1_prompt_results.csv.`;

    if (retRows.length) {
      const methods = ["bm25", "dense-pinecone", "hybrid-rrf", "hybrid+bge-base", "hybrid+minilm-l6"].filter((m) => retRows.some((r) => r.method === m && r.variant === prodVar));
      const MN = { "bm25": "BM25", "dense-pinecone": "Dense", "hybrid-rrf": "Hybrid (RRF)", "hybrid+bge-base": "Hybrid + bge-base", "hybrid+minilm-l6": "Hybrid + MiniLM" };
      const get = (m, k) => 100 * (retRows.find((r) => r.method === m && r.variant === prodVar)?.[k] ?? 0);
      $("#retHint").textContent = `Chunk variant ${prodVar} · ${RV.eval_set?.split(" ")[0] || ""}`;
      chart("chRet", { type: "bar", data: { labels: methods.map((m) => MN[m] || m), datasets: [
        { label: "Recall@1", data: methods.map((m) => get(m, "doc_R@1")), backgroundColor: "#b9d7d2", borderRadius: 3 },
        { label: "Recall@3", data: methods.map((m) => get(m, "doc_R@3")), backgroundColor: "#5fa59a", borderRadius: 3 },
        { label: "Recall@5", data: methods.map((m) => get(m, "doc_R@5")), backgroundColor: "#0f6e64", borderRadius: 3 }] },
        options: { maintainAspectRatio: false, scales: { y: { min: 50, max: 100, grid, ticks: { callback: (v) => v + "%" } }, x: { grid: { display: false } } },
          plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt1(c.raw)}%` } } } } });
      const lat = RV.rerank_latency_ms_p50_p95 || {};
      $("#retNote").textContent = `Inside the agent runs the gold document was retrieved for ${fmt1(m1.gold)}% (M1 run ${m1.r.run}) and ${fmt1(m2.gold)}% (M2 run ${m2.r.run}) of questions, below the offline ${prodRow ? fmt1(100 * prodRow["doc_R@5"]) : "?"}%, because the agents write their own search queries. Reranker latency p50: MiniLM ${lat["minilm-l6"]?.[0] ?? "?"} ms, bge-base ${lat["bge-base"]?.[0] ?? "?"} ms${RP ? `; production p50 ${RP.latency_p50_ms} ms, ${RP.degraded_queries} degraded queries` : ""}.`;
      const allM = [...new Set(retRows.map((r) => r.method))], vars = [...new Set(retRows.map((r) => r.variant))];
      $("#rettbl").innerHTML = `<thead><tr><th>Method</th>${vars.map((v) => `<th class="num">${v} R@5</th><th class="num">${v} MRR</th>`).join("")}</tr></thead><tbody>` +
        allM.map((m) => `<tr${m === "hybrid+" + prodRr ? ' style="font-weight:600"' : ""}><td>${esc(m)}${m === "hybrid+" + prodRr ? " · production" : ""}</td>${vars.map((v) => { const r = retRows.find((x) => x.method === m && x.variant === v);
          return r ? `<td class="num">${fmt1(100 * r["doc_R@5"])}%</td><td class="num">${r.doc_MRR.toFixed(3)}</td>` : `<td class="num">–</td><td class="num">–</td>`; }).join("")}</tr>`).join("") + "</tbody>";
    }

    const q = Object.fromEntries((m2 || m1).r.rows.map((x) => [+x.id, x]));
    const okW1 = (id) => strats.some((k) => w1[k].by[id]?.det_correct);
    const okAg = (id) => [m1, m2].some((a) => a.by[id]?.det_correct);
    const dot = (v) => `<span class="dot ${v ? "ok" : "no"}" title="${v ? "correct" : "not correct"}"></span>`;
    const draw = () => {
      const f = $("#plFilter").value;
      const list = [...ids].sort((a, b) => a - b).filter((id) => !f || (f === "fixed" ? !okW1(id) && okAg(id) : f === "regress" ? okW1(id) && ![m1, m2].some((a) => a.by[id]?.det_correct) : !okW1(id) && !okAg(id)));
      $("#plShown").textContent = `${list.length} of ${ids.size}`;
      $("#pqtbl").innerHTML = `<thead><tr><th>Q</th><th>Question</th><th>Difficulty</th>${strats.map((k) => `<th class="c">${SN[k].split(" ")[0]}</th>`).join("")}<th class="c">M1 r${m1.r.run}</th><th class="c">M2 r${m2.r.run}</th></tr></thead><tbody>` +
        list.map((id) => `<tr data-id="${id}" tabindex="0"><td class="num">${id}</td><td class="q">${esc(q[id]?.query || w1[strats[0]].by[id]?.prediction)}</td><td>${esc(q[id]?.difficulty || "")}</td>${strats.map((k) => `<td class="c">${dot(w1[k].by[id]?.det_correct)}</td>`).join("")}<td class="c">${dot(m1.by[id]?.det_correct)}</td><td class="c">${dot(m2.by[id]?.det_correct)}</td></tr>`).join("") + "</tbody>";
      document.querySelectorAll("#pqtbl tbody tr").forEach((tr) => { const go = () => openQ(+tr.dataset.id); tr.addEventListener("click", go); tr.addEventListener("keydown", (e) => e.key === "Enter" && go()); });
    };
    const openQ = (id) => {
      const g = q[id]; const v = (b) => b ? `<span class="pill p-ok">correct</span>` : `<span class="pill p-bad">not correct</span>`;
      $("#dTitle").textContent = `Q${id} · Week 1 → agents`;
      $("#dBody").innerHTML = `<div class="sec"><h3>Question</h3><div class="box">${esc(g?.query)}</div></div><div class="sec"><h3>Gold answer</h3><div class="box">${esc(g?.gold_answer)}</div></div>` +
        strats.map((k) => { const r = w1[k].by[id]; return `<div class="sec"><h3>Week 1 · ${SN[k]}</h3>${v(r?.det_correct)} <span class="pill p-mute">F1 ${r?.token_f1 ?? "–"}</span><div class="box" style="margin-top:8px">${esc(r?.prediction)}</div></div>`; }).join("") +
        [m1, m2].map((a) => { const r = a.by[id]; return `<div class="sec"><h3>${esc(a.r.label)}</h3>${v(r?.det_correct)} ${judgePill(r?.judge)} ${failPill(r?.failure)}<div class="box" style="margin-top:8px">${esc(r?.answer)}</div></div>`; }).join("");
      drawer.hidden = false; bg.hidden = false; drawer.setAttribute("aria-hidden", "false"); $("#dClose").focus();
    };
    $("#plFilter").addEventListener("input", draw); draw();
  }

  function select(id) { run = D.runs.find((r) => r.run_id === id) || order[0]; if (!run) return; overview(run.rows); renderTable(); }
  if (order.length) { select(order[0].run_id); compare(); }
  spansView();
  pipeline();
})();
