const state = {
  apiBaseUrl: (window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || "",
  token: localStorage.getItem("adminToken") || "",
  deviceStateIntervalId: null,
  selectedDeviceId: localStorage.getItem("selectedDeviceId") || "",
};

const deviceStateRefreshIntervalMs = 1000;

const page = document.body.dataset.page || "";
const currentPath = window.location.pathname;
const elements = {
  apiBaseUrlValue: document.getElementById("apiBaseUrlValue"),
  healthButton: document.getElementById("healthButton"),
  healthOutput: document.getElementById("healthOutput"),
  connectionBadge: document.getElementById("connectionBadge"),
  authBadge: document.getElementById("authBadge"),
  dashboardHint: document.getElementById("dashboardHint"),
  logoutButton: document.getElementById("logoutButton"),
  loginForm: document.getElementById("loginForm"),
  loginOutput: document.getElementById("loginOutput"),
  deviceForm: document.getElementById("deviceForm"),
  deviceOutput: document.getElementById("deviceOutput"),
  deviceStateBadge: document.getElementById("deviceStateBadge"),
  deviceStateButton: document.getElementById("deviceStateButton"),
  deviceStateAutoButton: document.getElementById("deviceStateAutoButton"),
  deviceStateOutput: document.getElementById("deviceStateOutput"),
  stateDeviceId: document.getElementById("stateDeviceId"),
  stateIsActiveCard: document.getElementById("stateIsActiveCard"),
  stateIsOnlineCard: document.getElementById("stateIsOnlineCard"),
  stateWaterValueCard: document.getElementById("stateWaterValueCard"),
  stateWaterDetectedCard: document.getElementById("stateWaterDetectedCard"),
  stateRelayOpenCard: document.getElementById("stateRelayOpenCard"),
  stateDesiredRelayOpenCard: document.getElementById("stateDesiredRelayOpenCard"),
  stateAutoCloseCard: document.getElementById("stateAutoCloseCard"),
  stateLastSeenCard: document.getElementById("stateLastSeenCard"),
  stateIsActive: document.getElementById("stateIsActive"),
  stateIsOnline: document.getElementById("stateIsOnline"),
  stateWaterValue: document.getElementById("stateWaterValue"),
  stateWaterDetected: document.getElementById("stateWaterDetected"),
  stateRelayOpen: document.getElementById("stateRelayOpen"),
  stateDesiredRelayOpen: document.getElementById("stateDesiredRelayOpen"),
  stateAutoClose: document.getElementById("stateAutoClose"),
  stateLastSeen: document.getElementById("stateLastSeen"),
  stateFirmware: document.getElementById("stateFirmware"),
  stateIp: document.getElementById("stateIp"),
  stateRssi: document.getElementById("stateRssi"),
  relayOpenButton: document.getElementById("relayOpenButton"),
  relayCloseButton: document.getElementById("relayCloseButton"),
  autoCloseCheckbox: document.getElementById("autoCloseCheckbox"),
  saveRelaySettingsButton: document.getElementById("saveRelaySettingsButton"),
  deviceId: document.getElementById("deviceId"),
  deviceSecret: document.getElementById("deviceSecret"),
};

function setBadge(node, label, tone) {
  node.textContent = label;
  node.className = `badge ${tone}`;
}

function writeOutput(node, payload) {
  node.textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
}

function setText(node, value) {
  if (node) {
    node.textContent = value;
  }
}

function setCardTone(node, tone) {
  if (!node) {
    return;
  }
  node.classList.remove("is-good", "is-warn", "is-live");
  if (tone) {
    node.classList.add(tone);
  }
}

function formatTimestamp(value) {
  if (!value) {
    return "Never";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString();
}

function buildUrl(path) {
  return `${state.apiBaseUrl.replace(/\/+$/, "")}${path}`;
}

function navigateTo(relativePath) {
  const basePath = currentPath.replace(/[^/]*$/, "");
  window.location.href = `${basePath}${relativePath}`;
}

function requireAuth() {
  if (page !== "dashboard" || state.token) {
    return;
  }

  const next = encodeURIComponent("./dashboard.html");
  navigateTo(`auth.html?next=${next}`);
}

function getNextPath() {
  const params = new URLSearchParams(window.location.search);
  const next = params.get("next");
  if (!next) {
    return "dashboard.html";
  }

  if (next.startsWith("http://") || next.startsWith("https://") || next.startsWith("//")) {
    return "dashboard.html";
  }

  return next.replace(/^\.?\//, "");
}

async function request(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  const response = await fetch(buildUrl(path), {
    ...options,
    headers,
  });

  const text = await response.text();
  let data = null;

  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!response.ok) {
    const detail = data && typeof data === "object" ? data : { detail: data || response.statusText };
    throw new Error(JSON.stringify(detail, null, 2));
  }

  return data;
}

function resetDeviceStateSummary() {
  setText(elements.stateIsActive, "-");
  setText(elements.stateIsOnline, "-");
  setText(elements.stateWaterValue, "-");
  setText(elements.stateWaterDetected, "-");
  setText(elements.stateRelayOpen, "-");
  setText(elements.stateDesiredRelayOpen, "-");
  setText(elements.stateAutoClose, "-");
  setText(elements.stateLastSeen, "-");
  setText(elements.stateFirmware, "-");
  setText(elements.stateIp, "-");
  setText(elements.stateRssi, "-");
  if (elements.autoCloseCheckbox) {
    elements.autoCloseCheckbox.checked = false;
  }
  setCardTone(elements.stateIsActiveCard, null);
  setCardTone(elements.stateIsOnlineCard, null);
  setCardTone(elements.stateWaterValueCard, null);
  setCardTone(elements.stateWaterDetectedCard, null);
  setCardTone(elements.stateRelayOpenCard, null);
  setCardTone(elements.stateDesiredRelayOpenCard, null);
  setCardTone(elements.stateAutoCloseCard, null);
  setCardTone(elements.stateLastSeenCard, null);
}

function renderDeviceState(data) {
  setText(elements.stateIsActive, data.is_active ? "Yes" : "No");
  setText(elements.stateIsOnline, data.online ? "Online" : "Offline");
  setText(elements.stateWaterValue, data.last_water_value ?? "-");
  setText(elements.stateWaterDetected, data.water_detected ? "Detected" : "Dry");
  setText(elements.stateRelayOpen, data.relay_open ? "Open" : "Closed");
  setText(elements.stateDesiredRelayOpen, data.desired_relay_open ? "Open" : "Closed");
  setText(elements.stateAutoClose, data.auto_close_on_water_detect ? "Enabled" : "Disabled");
  setText(elements.stateLastSeen, formatTimestamp(data.last_seen_at));
  setText(elements.stateFirmware, data.firmware_version || "-");
  setText(elements.stateIp, data.last_ip || "-");
  setText(elements.stateRssi, data.last_rssi ?? "-");
  if (elements.autoCloseCheckbox) {
    elements.autoCloseCheckbox.checked = Boolean(data.auto_close_on_water_detect);
  }

  setCardTone(elements.stateIsActiveCard, data.is_active ? "is-good" : "is-warn");
  setCardTone(elements.stateIsOnlineCard, data.online ? "is-live" : "is-warn");
  setCardTone(elements.stateWaterValueCard, "is-live");
  setCardTone(elements.stateWaterDetectedCard, data.water_detected ? "is-warn" : "is-good");
  setCardTone(elements.stateRelayOpenCard, data.relay_open ? "is-live" : null);
  setCardTone(elements.stateDesiredRelayOpenCard, data.desired_relay_open ? "is-live" : null);
  setCardTone(elements.stateAutoCloseCard, data.auto_close_on_water_detect ? "is-good" : null);
  setCardTone(elements.stateLastSeenCard, data.online ? "is-live" : null);
}

function getSelectedDeviceId() {
  if (!elements.stateDeviceId) {
    return "";
  }
  return elements.stateDeviceId.value.trim();
}

function saveSelectedDeviceId(value) {
  state.selectedDeviceId = value;
  localStorage.setItem("selectedDeviceId", value);
}

async function fetchDeviceState() {
  const deviceId = getSelectedDeviceId();

  if (!state.apiBaseUrl) {
    setBadge(elements.deviceStateBadge, "Missing config", "error");
    writeOutput(elements.deviceStateOutput, "Set window.APP_CONFIG.API_BASE_URL in config.js");
    return;
  }

  if (!state.token) {
    setBadge(elements.deviceStateBadge, "No token", "error");
    writeOutput(elements.deviceStateOutput, "Login first to fetch device state.");
    return;
  }

  if (!deviceId) {
    setBadge(elements.deviceStateBadge, "Missing ID", "error");
    writeOutput(elements.deviceStateOutput, "Enter a device ID to check its state.");
    return;
  }

  writeOutput(elements.deviceStateOutput, `Checking state for ${deviceId} ...`);
  try {
    const data = await request(`/api/v1/devices/${encodeURIComponent(deviceId)}/state`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${state.token}`,
      },
    });
    setBadge(elements.deviceStateBadge, data.online ? "Online" : "Offline", data.online ? "success" : "error");
    renderDeviceState(data);
    writeOutput(elements.deviceStateOutput, data);
  } catch (error) {
    setBadge(elements.deviceStateBadge, "Unavailable", "error");
    resetDeviceStateSummary();
    writeOutput(elements.deviceStateOutput, error.message);
  }
}

async function updateRelaySettings(payload) {
  const deviceId = elements.stateDeviceId ? elements.stateDeviceId.value.trim() : "";

  if (!state.apiBaseUrl) {
    writeOutput(elements.deviceStateOutput, "Set window.APP_CONFIG.API_BASE_URL in config.js");
    return;
  }
  if (!state.token) {
    writeOutput(elements.deviceStateOutput, "Login first to control the relay.");
    return;
  }
  if (!deviceId) {
    writeOutput(elements.deviceStateOutput, "Enter a device ID first.");
    return;
  }

  writeOutput(elements.deviceStateOutput, `Updating relay settings for ${deviceId} ...`);
  try {
    const data = await request(`/api/v1/devices/${encodeURIComponent(deviceId)}/relay`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${state.token}`,
      },
      body: JSON.stringify(payload),
    });
    writeOutput(elements.deviceStateOutput, data);
    await fetchDeviceState();
  } catch (error) {
    writeOutput(elements.deviceStateOutput, error.message);
  }
}

function toggleDeviceStateAutoRefresh() {
  if (state.deviceStateIntervalId) {
    window.clearInterval(state.deviceStateIntervalId);
    state.deviceStateIntervalId = null;
    elements.deviceStateAutoButton.textContent = "Start Auto Refresh";
    return;
  }

  fetchDeviceState();
  state.deviceStateIntervalId = window.setInterval(fetchDeviceState, deviceStateRefreshIntervalMs);
  elements.deviceStateAutoButton.textContent = "Stop Auto Refresh";
}

function startDeviceStateAutoRefresh() {
  if (!elements.deviceStateAutoButton || state.deviceStateIntervalId) {
    return;
  }
  fetchDeviceState();
  state.deviceStateIntervalId = window.setInterval(fetchDeviceState, deviceStateRefreshIntervalMs);
  elements.deviceStateAutoButton.textContent = "Stop Auto Refresh";
}

function syncUi() {
  if (elements.apiBaseUrlValue) {
    elements.apiBaseUrlValue.textContent = state.apiBaseUrl || "Not configured";
  }

  if (elements.stateDeviceId && state.selectedDeviceId) {
    elements.stateDeviceId.value = state.selectedDeviceId;
  }

  if (elements.authBadge && state.token) {
    setBadge(elements.authBadge, "Token saved", "success");
  } else if (elements.authBadge) {
    setBadge(elements.authBadge, "Logged out", "neutral");
  }

  if (elements.loginOutput && state.token) {
    writeOutput(elements.loginOutput, { access_token: state.token });
  } else if (elements.loginOutput) {
    writeOutput(elements.loginOutput, "No token yet.");
  }

  if (elements.dashboardHint) {
    elements.dashboardHint.textContent = state.token
      ? "Admin token found in local storage. You can create devices immediately."
      : "Login on the auth page before creating devices.";
  }
}

if (elements.healthButton) {
  elements.healthButton.addEventListener("click", async () => {
    if (!state.apiBaseUrl) {
      setBadge(elements.connectionBadge, "Missing config", "error");
      writeOutput(elements.healthOutput, "Set window.APP_CONFIG.API_BASE_URL in config.js");
      return;
    }
    writeOutput(elements.healthOutput, `Checking ${buildUrl("/health")} ...`);
    try {
      const data = await request("/health", { method: "GET" });
      setBadge(elements.connectionBadge, "Healthy", "success");
      writeOutput(elements.healthOutput, data);
    } catch (error) {
      setBadge(elements.connectionBadge, "Unavailable", "error");
      writeOutput(elements.healthOutput, error.message);
    }
  });
}

if (elements.loginForm) {
  elements.loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const payload = Object.fromEntries(formData.entries());

    writeOutput(elements.loginOutput, "Logging in ...");
    try {
      const data = await request("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.token = data.access_token;
      localStorage.setItem("adminToken", state.token);
      setBadge(elements.authBadge, "Logged in", "success");
      writeOutput(elements.loginOutput, data);
      window.setTimeout(() => {
        navigateTo(getNextPath());
      }, 400);
    } catch (error) {
      state.token = "";
      localStorage.removeItem("adminToken");
      setBadge(elements.authBadge, "Login failed", "error");
      writeOutput(elements.loginOutput, error.message);
    }
  });
}

if (elements.logoutButton) {
  elements.logoutButton.addEventListener("click", () => {
    if (state.deviceStateIntervalId) {
      window.clearInterval(state.deviceStateIntervalId);
      state.deviceStateIntervalId = null;
    }
    state.token = "";
    localStorage.removeItem("adminToken");
    navigateTo("auth.html");
  });
}

if (elements.deviceForm) {
  elements.deviceForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    if (!state.token) {
      writeOutput(elements.deviceOutput, "Login first to get an admin token.");
      return;
    }

    const formData = new FormData(event.currentTarget);
    const payload = Object.fromEntries(formData.entries());
    if (!payload.name) {
      delete payload.name;
    }

    writeOutput(elements.deviceOutput, "Creating device ...");
    try {
      const data = await request("/api/v1/admin/devices", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${state.token}`,
        },
        body: JSON.stringify(payload),
      });
      writeOutput(elements.deviceOutput, data);
      if (elements.stateDeviceId) {
        elements.stateDeviceId.value = payload.device_id;
        saveSelectedDeviceId(payload.device_id);
      }
      startDeviceStateAutoRefresh();
    } catch (error) {
      writeOutput(elements.deviceOutput, error.message);
    }
  });
}

if (elements.deviceId && elements.stateDeviceId) {
  elements.deviceId.addEventListener("input", (event) => {
    elements.stateDeviceId.value = event.target.value;
    saveSelectedDeviceId(event.target.value.trim());
  });
}

if (elements.stateDeviceId) {
  elements.stateDeviceId.addEventListener("input", (event) => {
    saveSelectedDeviceId(event.target.value.trim());
    if (state.deviceStateIntervalId) {
      fetchDeviceState();
    }
  });
}

if (elements.deviceStateButton) {
  elements.deviceStateButton.addEventListener("click", fetchDeviceState);
}

if (elements.deviceStateAutoButton) {
  elements.deviceStateAutoButton.addEventListener("click", toggleDeviceStateAutoRefresh);
}

if (elements.relayOpenButton) {
  elements.relayOpenButton.addEventListener("click", () => {
    updateRelaySettings({ relay_open: true });
  });
}

if (elements.relayCloseButton) {
  elements.relayCloseButton.addEventListener("click", () => {
    updateRelaySettings({ relay_open: false });
  });
}

if (elements.saveRelaySettingsButton) {
  elements.saveRelaySettingsButton.addEventListener("click", () => {
    updateRelaySettings({
      auto_close_on_water_detect: Boolean(elements.autoCloseCheckbox && elements.autoCloseCheckbox.checked),
    });
  });
}

requireAuth();
syncUi();

if (page === "dashboard" && state.token && state.selectedDeviceId) {
  startDeviceStateAutoRefresh();
}
