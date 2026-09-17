import { HRWorkforceClient } from "/ui-integration/assets/hr-ui-client.js";

const client = new HRWorkforceClient({
  baseUrl: "",
  getOrganizationId: () => localStorage.getItem("hr_selected_org"),
});

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function main() {
  try {
    const data = await client.bootstrap();
    document.querySelector("#summary").innerHTML = [
      ["Tenant", data.tenant_id],
      ["Graph", data.graph_available ? "Available" : "Fallback"],
      ["Runtime", data.metadata.runtime_mode],
      ["Visible modules", data.navigation.length],
    ].map(([label, value]) => `<div class="summary-card"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");

    document.querySelector("#nav-grid").innerHTML = data.navigation.map(item => `
      <article class="nav-card">
        <h3>${esc(item.label)}</h3>
        <p>${esc(item.description || "")}</p>
        <span class="badge">${esc(item.route_key)}${item.audience === "admin" ? " · admin" : ""}</span>
      </article>
    `).join("");

    document.querySelector("#runtime-table").innerHTML = `
      <table>
        <thead><tr><th>Service</th><th>State</th><th>Active source</th><th>Graph</th><th>Fallback</th></tr></thead>
        <tbody>
          ${data.runtime_services.map(item => `
            <tr>
              <td>${esc(item.service)}</td>
              <td>${esc(item.state)}</td>
              <td>${esc(item.active_source)}</td>
              <td class="${item.graph_capable ? "ok" : "warn"}">${item.graph_capable ? "Yes" : "No"}</td>
              <td>${item.fallback_enabled ? "Enabled" : "No"}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>`;

    document.querySelector("#contract").textContent = JSON.stringify({
      step: data.step,
      tenant_id: data.tenant_id,
      auth_enabled: data.auth_enabled,
      ui_api_contract_preserved: data.ui_api_contract_preserved,
      feature_flags: data.feature_flags,
      metadata: data.metadata,
      warnings: data.warnings,
    }, null, 2);
  } catch (error) {
    document.querySelector("#summary").innerHTML = `<div class="error">${esc(error.message)}</div>`;
  }
}

main();
