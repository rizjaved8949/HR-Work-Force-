/**
 * Step 11 drop-in browser client for the existing HR Workforce UI.
 *
 * No token storage policy is imposed here. Pass getAccessToken() from the
 * application's existing auth/session layer.
 */
export class HRWorkforceClient {
  constructor({ baseUrl = "", getAccessToken = null } = {}) {
    this.baseUrl = String(baseUrl || "").replace(/\/$/, "");
    this.getAccessToken = getAccessToken;
  }

  async _token() {
    if (!this.getAccessToken) return null;
    return await this.getAccessToken();
  }

  async request(path, { method = "GET", body = undefined, headers = {}, signal = undefined } = {}) {
    const token = await this._token();
    const requestHeaders = { Accept: "application/json", ...headers };
    if (body !== undefined) requestHeaders["Content-Type"] = "application/json";
    if (token) requestHeaders.Authorization = `Bearer ${token}`;

    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: requestHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });

    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      const message = typeof payload === "object" && payload?.detail
        ? payload.detail
        : `Request failed (${response.status})`;
      const error = new Error(message);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  bootstrap() {
    return this.request("/ui-integration/bootstrap");
  }

  navigation() {
    return this.request("/ui-integration/navigation");
  }

  runtime() {
    return this.request("/ui-integration/runtime");
  }

  apiContract() {
    return this.request("/ui-integration/api-contract");
  }

  searchEmployee(input) {
    return this.request("/tools/employee-search", { method: "POST", body: input });
  }

  attrition(input) {
    return this.request("/pipeline/attrition", { method: "POST", body: input });
  }

  replacement(input) {
    return this.request("/pipeline/replacement", { method: "POST", body: input });
  }

  headcount(input) {
    return this.request("/pipeline/headcount", { method: "POST", body: input });
  }

  performance(input) {
    return this.request("/pipeline/performance", { method: "POST", body: input });
  }

  simulationScenarios() {
    return this.request("/api/v1/simulations/scenarios");
  }

  runSimulation(input) {
    return this.request("/api/v1/simulations/run", { method: "POST", body: input });
  }

  decisionCases(query = "") {
    return this.request(`/api/v1/decision-cases${query ? `?${query}` : ""}`);
  }

  chat(input) {
    return this.request("/chat", { method: "POST", body: input });
  }
}

export default HRWorkforceClient;
