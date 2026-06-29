const preview = document.getElementById("preview");
const deviceInfo = document.getElementById("device-info");
const controlsForm = document.getElementById("controls-form");
const formatSelect = document.getElementById("format-select");
const rtspToggle = document.getElementById("rtsp-toggle");
const rtspUrl = document.getElementById("rtsp-url");
const ledOn = document.getElementById("led-on");

let state = null;
let debounceTimers = new Map();

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

function startPreview() {
  if (!preview.src) {
    preview.src = "/preview.mjpg";
  }
}

function reloadPreview() {
  preview.src = "";
  requestAnimationFrame(() => {
    preview.src = `/preview.mjpg?t=${Date.now()}`;
  });
}

function renderDeviceInfo(data) {
  const info = data.info;
  const fmt = data.format;
  deviceInfo.textContent = `${info.card} · ${info.device} · ${fmt.width}x${fmt.height} ${fmt.pixel_format}`;
}

function renderFormats(formats, stream) {
  formatSelect.innerHTML = "";
  for (const f of formats) {
    const opt = document.createElement("option");
    opt.value = JSON.stringify({
      width: f.width,
      height: f.height,
      pixel_format: f.pixel_format,
    });
    opt.textContent = f.label;
    if (
      f.width === stream.width &&
      f.height === stream.height &&
      f.pixel_format === stream.pixel_format
    ) {
      opt.selected = true;
    }
    formatSelect.appendChild(opt);
  }
}

function renderLed(led) {
  if (!led || !ledOn) return;
  ledOn.checked = Boolean(led.on);
}

function renderControl(ctrl) {
  const row = document.createElement("div");
  row.className = `control-row${ctrl.inactive ? " inactive" : ""}`;
  row.dataset.name = ctrl.name;

  const label = document.createElement("label");
  label.className = "name";
  label.textContent = ctrl.name.replace(/_/g, " ");
  row.appendChild(label);

  let input;
  if (ctrl.type === "bool") {
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(ctrl.value);
    input.disabled = ctrl.inactive;
    input.addEventListener("change", () => setControl(ctrl.name, input.checked ? 1 : 0));
  } else if (ctrl.type === "menu") {
    input = document.createElement("select");
    input.disabled = ctrl.inactive;
    for (const optData of ctrl.menu_options || []) {
      const opt = document.createElement("option");
      opt.value = optData.value;
      opt.textContent = optData.label;
      if (Number(optData.value) === Number(ctrl.value)) opt.selected = true;
      input.appendChild(opt);
    }
    input.addEventListener("change", () => setControl(ctrl.name, Number(input.value)));
  } else {
    input = document.createElement("input");
    input.type = "range";
    input.min = ctrl.min ?? 0;
    input.max = ctrl.max ?? 100;
    input.step = ctrl.step ?? 1;
    input.value = ctrl.value;
    input.disabled = ctrl.inactive;
    input.addEventListener("input", () => {
      valueEl.textContent = `${ctrl.name}: ${input.value}`;
      debounceSetControl(ctrl.name, Number(input.value));
    });
  }
  row.appendChild(input);

  const valueEl = document.createElement("div");
  valueEl.className = "value";
  valueEl.textContent = ctrl.display || String(ctrl.value);
  row.appendChild(valueEl);

  return row;
}

function debounceSetControl(name, value) {
  clearTimeout(debounceTimers.get(name));
  debounceTimers.set(
    name,
    setTimeout(() => setControl(name, value), 120),
  );
}

async function setControl(name, value) {
  try {
    await api("/api/controls", {
      method: "PATCH",
      body: JSON.stringify({ name, value }),
    });
    await refresh(false);
  } catch (err) {
    console.error(err);
  }
}

function renderControls(controls) {
  controlsForm.innerHTML = "";
  for (const ctrl of controls) {
    controlsForm.appendChild(renderControl(ctrl));
  }
}

function updateRtspUi(stream) {
  const active = stream.rtsp_active;
  rtspToggle.textContent = active ? "RTSP stoppen" : "RTSP starten";
  rtspToggle.classList.toggle("active", active);
  rtspUrl.textContent = active ? stream.rtsp_public_url : "";
}

async function refresh(reloadVideo = true) {
  state = await api("/api/camera");
  renderDeviceInfo(state);
  renderFormats(state.formats, state.stream);
  renderControls(state.controls);
  renderLed(state.led);
  updateRtspUi(state.stream);
  if (reloadVideo) startPreview();
}

formatSelect.addEventListener("change", async () => {
  const fmt = JSON.parse(formatSelect.value);
  await api("/api/format", { method: "POST", body: JSON.stringify(fmt) });
  await refresh(false);
});

ledOn.addEventListener("change", async () => {
  try {
    await api("/api/led", {
      method: "PATCH",
      body: JSON.stringify({ on: ledOn.checked }),
    });
  } catch (err) {
    console.error(err);
    await refresh(false);
  }
});

function streamsStopPreview() {
  preview.src = "";
}

rtspToggle.addEventListener("click", async () => {
  const active = state?.stream?.rtsp_active;
  if (active) {
    await api("/api/stream/rtsp/stop", { method: "POST" });
    reloadPreview();
  } else {
    preview.src = "";
    await api("/api/stream/rtsp/start", { method: "POST" });
  }
  await refresh(false);
});

refresh(true);
setInterval(() => refresh(false), 5000);
