const state = { selected: localStorage.getItem("hr_selected_org") || "" };

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function request(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  const token = localStorage.getItem("access_token") || localStorage.getItem("hr_access_token");
  if (token) headers.Authorization = `Bearer ${token}`;
  if (state.selected) headers["X-Organization-ID"] = state.selected;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

function show(data) {
  document.querySelector("#output").textContent = JSON.stringify(data, null, 2);
}

function selectedTenant() {
  return document.querySelector("#org-select").value || state.selected;
}

async function refresh(showPayload = true) {
  const data = await request("/organization-onboarding/api/bootstrap");
  const orgs = data.organizations || [];
  const select = document.querySelector("#org-select");
  select.innerHTML = orgs.map(o => `<option value="${esc(o.tenant_id)}">${esc(o.name)} · ${esc(o.tenant_id)} · ${esc(o.status)}</option>`).join("");
  if (state.selected && orgs.some(o => o.tenant_id === state.selected)) select.value = state.selected;
  if (!state.selected && orgs[0]) state.selected = orgs[0].tenant_id;
  document.querySelector("#summary").innerHTML = [
    ["Organizations", orgs.length],
    ["Selected tenant", state.selected || "None"],
    ["Create allowed", data.can_create_organization ? "Yes" : "No"],
    ["Tenant header", data.tenant_header],
  ].map(([label,value]) => `<div class="summary-card"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
  if (showPayload) show(data);
}

async function openOrg() {
  const tenant = selectedTenant();
  if (!tenant) return;
  state.selected = tenant;
  localStorage.setItem("hr_selected_org", tenant);
  const data = await request(`/organization-onboarding/api/organizations/${encodeURIComponent(tenant)}`);
  const r = data.readiness;
  document.querySelector("#org-detail").innerHTML = `
    <span class="chip">${esc(data.organization.status)}</span>
    <div><strong>${esc(data.organization.name)}</strong> · ${esc(data.organization.tenant_id)}</div>
    <div class="muted">Datasets ${r.dataset_count} · Approved ${r.approved_mapping_count} · Loaded ${r.loaded_dataset_count} · Graph nodes ${r.graph_node_count} · relationships ${r.graph_relationship_count}</div>
    <div class="muted">Ready to activate: ${r.ready_to_activate ? "Yes" : "No"}</div>`;
  const datasetSelect = document.querySelector("#dataset-select");
  datasetSelect.innerHTML = '<option value="">Select a dataset</option>' +
    (data.organization.datasets || []).map(item =>
      `<option value="${esc(item.dataset_id)}">${esc(item.source_object)} · ${esc(item.dataset_id)} · ${esc(item.status)}</option>`
    ).join("");
  show(data);
  await refresh(false);
}

document.querySelector("#refresh").addEventListener("click", refresh);
document.querySelector("#load-org").addEventListener("click", openOrg);

document.querySelector("#create-org").addEventListener("submit", async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const data = await request("/organization-onboarding/api/organizations", {
      method: "POST",
      body: Object.fromEntries(form.entries()),
    });
    state.selected = data.tenant_id;
    localStorage.setItem("hr_selected_org", state.selected);
    await refresh(false);
    await openOrg();
  } catch (error) { show({ error: error.message }); }
});

document.querySelector("#register-dataset").addEventListener("submit", async event => {
  event.preventDefault();
  const tenant = state.selected || selectedTenant();
  if (!tenant) return show({ error: "Select an organization first." });
  const form = new FormData(event.currentTarget);
  let rows;
  try { rows = JSON.parse(form.get("rows")); }
  catch { return show({ error: "Rows JSON must be a valid JSON array." }); }
  try {
    const data = await request(`/organization-onboarding/api/organizations/${encodeURIComponent(tenant)}/datasets/records`, {
      method: "POST",
      body: {
        source_system: form.get("source_system"),
        source_object: form.get("source_object"),
        source_format: "records",
        rows,
      },
    });
    show(data);
    await openOrg();
  } catch (error) { show({ error: error.message }); }
});


function datasetId() {
  return document.querySelector("#dataset-select").value;
}

async function datasetAction(suffix, { method = "GET", body } = {}) {
  const tenant = state.selected || selectedTenant();
  const dataset = datasetId();
  if (!tenant) return show({ error: "Select an organization first." });
  if (!dataset) return show({ error: "Select a dataset first." });
  try {
    const data = await request(
      `/organization-onboarding/api/organizations/${encodeURIComponent(tenant)}/datasets/${encodeURIComponent(dataset)}${suffix}`,
      { method, body },
    );
    show(data);
    await openOrg();
    return data;
  } catch (error) { show({ error: error.message }); }
}

document.querySelector("#profile-dataset").addEventListener("click", () => datasetAction("/profile"));
document.querySelector("#suggest-dataset").addEventListener("click", () => datasetAction("/mapping-suggestions"));
document.querySelector("#validate-plan").addEventListener("click", () => datasetAction("/mapping-plan/validate"));
document.querySelector("#approve-plan").addEventListener("click", () => datasetAction("/mapping-plan/approve", { method: "POST" }));
document.querySelector("#dry-run").addEventListener("click", () => datasetAction("/dry-run"));

document.querySelector("#mapping-plan").addEventListener("submit", async event => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const parseArray = (name) => {
    const text = String(form.get(name) || "").trim();
    return text ? JSON.parse(text) : [];
  };
  try {
    await datasetAction("/mapping-plan", {
      method: "POST",
      body: {
        version: "1.0.0",
        property_mappings: parseArray("property_mappings"),
        entity_rules: parseArray("entity_rules"),
        relationship_mappings: parseArray("relationship_mappings"),
      },
    });
  } catch (error) { show({ error: error.message }); }
});

document.querySelector("#load-organization").addEventListener("click", async () => {
  const tenant = state.selected || selectedTenant();
  if (!tenant) return show({ error: "Select an organization first." });
  try {
    const data = await request(`/organization-onboarding/api/organizations/${encodeURIComponent(tenant)}/load`, { method: "POST" });
    show(data);
    await openOrg();
  } catch (error) { show({ error: error.message }); }
});

document.querySelector("#activate-organization").addEventListener("click", async () => {
  const tenant = state.selected || selectedTenant();
  if (!tenant) return show({ error: "Select an organization first." });
  try {
    const data = await request(`/organization-onboarding/api/organizations/${encodeURIComponent(tenant)}/activate`, { method: "POST" });
    show(data);
    await openOrg();
  } catch (error) { show({ error: error.message }); }
});

refresh().catch(error => show({ error: error.message }));
