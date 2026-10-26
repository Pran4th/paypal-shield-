let grid;

const riskCell = (p) => {
  const s = p.value || 0;
  const cls = s >= 60 ? "r-high" : s >= 40 ? "r-med" : "r-low";
  return `<span class="risk ${cls}">${s}</span>`;
};

const cols = [
  { field: "order_id", headerName: "Order", width: 120 },
  { field: "payer_name", headerName: "Buyer", width: 140 },
  { field: "description", headerName: "Item", flex: 1, minWidth: 180 },
  { field: "amount", headerName: "$", width: 90, valueFormatter: p => p.value?.toLocaleString("en-US", {style:"currency", currency:"USD", maximumFractionDigits:0}) },
  { field: "promised_eta", headerName: "Promised", width: 105 },
  { field: "updated_eta", headerName: "Now ETA", width: 105 },
  { field: "eta_slips", headerName: "Slips", width: 70 },
  { field: "days_since_buyer_contact", headerName: "Silent (d)", width: 95 },
  { field: "tracking_number", headerName: "Tracking", width: 130, valueFormatter: p => p.value || "—" },
  { field: "risk_score", headerName: "Risk", width: 85, cellRenderer: riskCell },
  { field: "risk_reasons", headerName: "Why", flex: 1, minWidth: 160, valueFormatter: p => (p.value||[]).join(" · ") },
];

async function api(path, method = "GET", body) {
  const r = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

function fmt$(n) { return "$" + (n || 0).toLocaleString("en-US", { maximumFractionDigits: 0 }); }

async function load() {
  const s = await api("/api/state");
  document.getElementById("mode-pill").textContent = s.demo_mode ? "DEMO MODE — seeded sandbox data" : "LIVE SANDBOX";
  document.getElementById("mode-pill").className = "pill" + (s.demo_mode ? " demo" : "");
  document.getElementById("s-protected").textContent = fmt$(s.protected_total);
  document.getElementById("s-orders").textContent = s.orders.length;
  document.getElementById("s-atrisk").textContent = s.orders.filter(o => o.risk_score >= 40).length;
  document.getElementById("s-proposals").textContent = s.interventions.filter(i => i.status === "proposed").length;
  document.getElementById("s-disputes").textContent = s.disputes.filter(d => d.status === "OPEN").length;

  if (!grid) {
    grid = agGrid.createGrid(document.getElementById("orders-grid"), {
      columnDefs: cols,
      rowData: s.orders,
      defaultColDef: { sortable: true, filter: true, resizable: true },
      animateRows: true,
    });
  } else {
    grid.setGridOption("rowData", s.orders);
  }

  renderInterventions(s.interventions.filter(i => i.status === "proposed"));
  renderDisputes(s.disputes);
  renderEvents(s.events);
}

function renderInterventions(items) {
  const el = document.getElementById("interventions");
  if (!items.length) { el.innerHTML = '<div class="empty">No open proposals — the agent is watching.</div>'; return; }
  el.innerHTML = items.map(i => `
    <div class="card">
      <div class="top"><span class="kind">${i.kind.replaceAll("_"," ")}</span><span class="tag ${i.status}">${i.status}</span></div>
      <div class="sum">${i.summary}</div>
      <div class="meta">${i.order_id}${i.amount ? " · " + fmt$(i.amount) : ""}</div>
      <div class="det">${i.detail}</div>
      <div class="btns">
        <button class="primary" onclick="act(${i.id},'approve')">Approve</button>
        <button onclick="act(${i.id},'reject')">Reject</button>
      </div>
    </div>`).join("");
}

function renderDisputes(list) {
  const el = document.getElementById("disputes");
  if (!list.length) { el.innerHTML = '<div class="empty">No disputes. That is the goal.</div>'; return; }
  el.innerHTML = list.map(d => `
    <div class="card">
      <div class="top">
        <span class="sum">${d.dispute_id}</span>
        <span class="tag ${d.evidence_status}">${d.evidence_status}</span>
      </div>
      <div class="meta">${d.reason} · ${fmt$(d.amount)} · stage ${d.stage}</div>
      <div class="meta">Response due <span class="due">${d.response_due || "—"}</span></div>
      ${d.draft_response ? `
        <details class="draftbox"><summary>AI-drafted response</summary><pre>${d.draft_response}</pre></details>
        <div class="btns">
          ${d.evidence_status === "draft" ? `<button class="primary" onclick="sendDispute('${d.dispute_id}')">Send to PayPal</button>` : ""}
        </div>` : `
        <div class="btns"><button onclick="draft('${d.dispute_id}')">Draft response</button></div>`}
    </div>`).join("");
}

function renderEvents(events) {
  document.getElementById("events").innerHTML = events.map(e =>
    `<div><b>${e.event_type}</b> · ${e.resource_id} · ${e.received_at}</div>`
  ).join("") || '<div class="empty">Waiting for events…</div>';
}

async function act(id, action) {
  await api(`/api/interventions/${id}/${action}`, "POST");
  await load();
}
async function draft(id) {
  await api(`/api/disputes/${id}/draft`, "POST");
  await load();
}
async function sendDispute(id) {
  await api(`/api/disputes/${id}/send`, "POST");
  await load();
}
async function refresh() {
  await api("/api/refresh", "POST");
  await load();
}

load();
setInterval(load, 15000);
