const state = { selected: localStorage.getItem("hr_selected_org") || "" };
const apiUrl = (path) => path;

function esc(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

async function request(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  const token = localStorage.getItem("access_token") || localStorage.getItem("hr_access_token");
  if (token) headers.Authorization = `Bearer ${token}`;
  if (state.selected) headers["X-Organization-ID"] = state.selected;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(apiUrl(path), { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text }; }
  if (!res.ok) throw new Error(data.detail || data.error || `Request failed (${res.status})`);
  return data;
}

function show(data) { document.querySelector("#output").textContent = JSON.stringify(data, null, 2); }
function selectedTenant() { return document.querySelector("#org-select").value || state.selected; }

function renderMappingTable(mapping) {
  const rows = mapping.property_mappings || [];
  const el = document.querySelector("#mapping-table");
  if (!rows.length) {
    el.innerHTML = '<span class="muted">No ontology properties were resolved.</span>';
    return;
  }
  el.innerHTML = `
    <div class="mini-row mini-head"><span>Source column</span><span>Ontology property</span></div>
    ${rows.map(item => `<div class="mini-row"><span>${esc(item.source_column)}</span><span>${esc(item.ontology_path)}</span></div>`).join("")}`;
}

function renderGraphPreview(preview) {
  const nodes = preview?.nodes || [];
  const relationships = preview?.relationships || [];
  const el = document.querySelector("#graph-preview");
  if (!nodes.length && !relationships.length) {
    el.innerHTML = '<span class="muted">No graph preview available.</span>';
    return;
  }
  el.innerHTML = `
    <p class="preview-label">Nodes</p>
    <div class="tag-wrap">${nodes.map(node => `<span class="tag good">${esc(node.entity_type)}</span>`).join("") || '<span class="muted">None</span>'}</div>
    <p class="preview-label">Relationships</p>
    <div class="edge-list">${relationships.map(edge => `<div class="edge-line"><span>${esc(edge.source_entity_type)}</span><b>— ${esc(edge.relation_type)} →</b><span>${esc(edge.target_entity_type)}</span></div>`).join("") || '<span class="muted">None</span>'}</div>`;
}

function renderSync(data) {
  const cards = document.querySelector("#sync-cards");
  const mapping = data.mapping || {};
  const graph = data.graph || {};
  const canonical = data.canonical || {};
  const raw = data.raw_supabase || {};
  cards.innerHTML = [
    ["Status", data.status || "-"],
    ["Rows", data.rows_received ?? "-"],
    ["Mapped", mapping.mapped_column_count ?? "-"],
    ["Raw-only", mapping.unmapped_column_count ?? "-"],
    ["Graph nodes", graph.nodes_after ?? "-"],
    ["Relationships", graph.relationships_after ?? "-"],
    ["Raw Supabase", raw.persisted ? "Stored" : "Disabled"],
  ].map(([label,value]) => `<div class="result-card"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");

  const mapped = mapping.mapped_columns || [];
  const unmapped = mapping.unmapped_columns || [];
  const pending = mapping.skipped_pending_semantic_columns || [];
  const types = canonical.entity_types || {};
  const rels = canonical.relationship_types || {};
  const readiness = data.readiness || {};
  document.querySelector("#mapping-result").innerHTML = `
      <div><h3>Mapped to ontology</h3><p>${mapped.length ? mapped.map(x => `<span class="tag good">${esc(x)}</span>`).join("") : '<span class="muted">None</span>'}</p></div>
      <div><h3>Preserved raw only</h3><p>${unmapped.length ? unmapped.map(x => `<span class="tag warn">${esc(x)}</span>`).join("") : '<span class="muted">None</span>'}</p>${pending.length ? `<p class="tiny">Pending semantics: ${pending.map(esc).join(", ")}</p>` : ""}</div>
      <div><h3>Node types written</h3><p>${Object.entries(types).map(([k,v]) => `<span class="tag">${esc(k)} · ${esc(v)}</span>`).join("") || '<span class="muted">None</span>'}</p></div>
      <div><h3>Relationship types</h3><p>${Object.entries(rels).map(([k,v]) => `<span class="tag rel">${esc(k)} · ${esc(v)}</span>`).join("") || '<span class="muted">None</span>'}</p></div>
      <div><h3>Supabase storage</h3><p class="tiny">Raw: <b>${esc(raw.datasets_table || "-")}</b> + <b>${esc(raw.rows_table || "-")}</b><br>Graph: <b>${esc(graph.kg_nodes_table || "kg_nodes")}</b> + <b>${esc(graph.kg_relationships_table || "kg_relationships")}</b></p></div>
      <div><h3>Organization readiness</h3><p class="tiny">Status: <b>${esc(data.organization_status || "-")}</b><br>Ready: <b>${esc(readiness.ready_to_activate ?? "-")}</b>${(readiness.blockers || []).length ? `<br>Blockers: ${esc(readiness.blockers.join(" | "))}` : ""}</p></div>`;

  renderMappingTable(mapping);
  renderGraphPreview(data.graph_preview || {});
  const tenant = data.tenant_id || state.selected || selectedTenant();
  const panel = document.querySelector("#sync-summary-panel");
  let action = document.querySelector("#open-live-tenant-graph");
  if (!action) {
    action = document.createElement("a");
    action.id = "open-live-tenant-graph";
    action.className = "live-graph-link";
    action.textContent = "Open this tenant in Ontology Studio - Live Graph";
    panel.appendChild(action);
  }
  action.href = `/ontology-studio?tenant_id=${encodeURIComponent(tenant)}`;
}

async function refresh(showPayload = false) {
  const data = await request("/organization-onboarding/api/bootstrap");
  const orgs = data.organizations || [];
  const select = document.querySelector("#org-select");
  select.innerHTML = orgs.map(o => `<option value="${esc(o.tenant_id)}">${esc(o.name)} · ${esc(o.tenant_id)} · ${esc(o.status)}</option>`).join("");
  if (state.selected && orgs.some(o => o.tenant_id === state.selected)) select.value = state.selected;
  if (!state.selected && orgs[0]) state.selected = orgs[0].tenant_id;
  if (state.selected) select.value = state.selected;
  document.querySelector("#summary").innerHTML = [
    ["Organizations", orgs.length], ["Selected tenant", state.selected || "None"], ["Auto sync", "Enabled"], ["Graph backend", data.graph_backend || "GraphRepository"],
  ].map(([label,value]) => `<div class="summary-card"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
  if (showPayload) show(data);
}

async function openOrg(showPayload = false) {
  const tenant = selectedTenant();
  if (!tenant) return;
  state.selected = tenant;
  localStorage.setItem("hr_selected_org", tenant);
  const data = await request(`/organization-onboarding/api/organizations/${encodeURIComponent(tenant)}`);
  const r = data.readiness;
  document.querySelector("#org-detail").innerHTML = `
    <span class="chip">${esc(data.organization.status)}</span>
    <div><strong>${esc(data.organization.name)}</strong> · ${esc(data.organization.tenant_id)}</div>
    <div class="muted">Datasets ${r.dataset_count} · Loaded ${r.loaded_dataset_count} · Graph nodes ${r.graph_node_count} · relationships ${r.graph_relationship_count}</div>`;
  await refresh(false);
  if (showPayload) show(data);
}

document.querySelector("#refresh").addEventListener("click", async () => { await refresh(false); await openOrg(false); });
document.querySelector("#load-org").addEventListener("click", () => openOrg(true));
document.querySelector("#org-select").addEventListener("change", () => openOrg(false));

document.querySelector("#create-org").addEventListener("submit", async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const data = await request("/organization-onboarding/api/organizations", { method: "POST", body: Object.fromEntries(form.entries()) });
    state.selected = data.tenant_id;
    localStorage.setItem("hr_selected_org", state.selected);
    show(data);
    await refresh(false);
    await openOrg(false);
  } catch (error) { show({ error: error.message }); }
});

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer); const chunkSize = 0x8000; let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) binary += String.fromCharCode(...bytes.subarray(i, Math.min(i + chunkSize, bytes.length)));
  return btoa(binary);
}

const fileInput = document.querySelector("#dataset-file");
fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  document.querySelector("#file-note").textContent = file ? `${file.name} · ${(file.size / 1024).toFixed(1)} KB` : "CSV, JSON, XLSX or XLSM · max 20 MB by default";
});

document.querySelector("#upload-dataset").addEventListener("submit", async event => {
  event.preventDefault();
  const tenant = state.selected || selectedTenant();
  if (!tenant) return show({ error: "Select an organization first." });
  const form = new FormData(event.currentTarget);
  const file = form.get("file");
  if (!(file instanceof File) || !file.name) return show({ error: "Choose a CSV, JSON, XLSX or XLSM file first." });

  const status = document.querySelector("#upload-status");
  const button = document.querySelector("#sync-button");
  button.disabled = true; button.textContent = "Syncing…";
  status.textContent = `Reading ${file.name}…`;
  try {
    const contentBase64 = arrayBufferToBase64(await file.arrayBuffer());
    status.textContent = `Uploading, mapping, validating and updating Supabase graph for ${file.name}…`;
    const data = await request(`/organization-onboarding/api/organizations/${encodeURIComponent(tenant)}/datasets/auto-sync`, {
      method: "POST",
      body: {
        filename: file.name,
        content_base64: contentBase64,
        source_system: String(form.get("source_system") || "browser_upload").trim() || "browser_upload",
        source_object: String(form.get("source_object") || file.name).trim() || file.name,
        sheet_name: String(form.get("sheet_name") || "").trim() || null,
      },
    });
    status.textContent = data.status === "synced"
      ? `Sync complete: ${data.rows_received} rows stored; ${data.mapping?.mapped_column_count ?? 0} columns mapped; graph now has ${data.graph?.nodes_after ?? "?"} nodes and ${data.graph?.relationships_after ?? "?"} relationships.`
      : `Sync stopped safely: ${data.message || data.status}`;
    renderSync(data); show(data); await openOrg(false);
  } catch (error) {
    status.textContent = `Sync failed: ${error.message}`; show({ error: error.message });
  } finally { button.disabled = false; button.textContent = "Upload & Sync Now"; }
});

(async () => { try { await refresh(false); await openOrg(false); } catch (error) { show({ error: error.message }); } })();
