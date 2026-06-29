const preview = document.getElementById("preview");
const deviceSelect = document.getElementById("device-select");
const deviceInfo = document.getElementById("device-info");
const controlsForm = document.getElementById("controls-form");
const formatSelect = document.getElementById("format-select");
const rtspToggle = document.getElementById("rtsp-toggle");
const rtspUrl = document.getElementById("rtsp-url");
const xuControls = document.getElementById("xu-controls");
const xuRescan = document.getElementById("xu-rescan");
const gpioPanel = document.getElementById("gpio-panel");
const gpioStatus = document.getElementById("gpio-status");
let gpioButtonsBuilt = false;

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
  const ids = info.bus_info ? ` · ${info.bus_info}` : "";
  deviceInfo.textContent = `${info.card} · ${info.device}${ids} · ${fmt.width}x${fmt.height} ${fmt.pixel_format}`;
}

function renderDeviceSelect(devices, activeDevice) {
  const prev = deviceSelect.value;
  deviceSelect.innerHTML = "";
  if (!devices?.length) {
    const opt = document.createElement("option");
    opt.textContent = "Keine Kamera";
    deviceSelect.appendChild(opt);
    deviceSelect.disabled = true;
    return;
  }
  deviceSelect.disabled = devices.length < 2;
  for (const dev of devices) {
    const opt = document.createElement("option");
    opt.value = dev.device;
    const usb = dev.usb_id ? ` [${dev.usb_id}]` : "";
    const sonix = dev.is_sonix ? " · Sonix" : "";
    opt.textContent = `${dev.device} — ${dev.card || dev.name}${usb}${sonix}`;
    if (dev.device === activeDevice) opt.selected = true;
    deviceSelect.appendChild(opt);
  }
  if (prev && prev !== activeDevice && [...deviceSelect.options].some((o) => o.value === prev)) {
    deviceSelect.value = prev;
  }
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

async function setXuControl(ctrl, valueBytes) {
  await api("/api/xu", {
    method: "PATCH",
    body: JSON.stringify({
      unit: ctrl.unit,
      selector: ctrl.selector,
      value_bytes: valueBytes,
    }),
  });
  await refresh(false);
}

function formatGpio(gpio) {
  return `En=0x${gpio.enable.toString(16).padStart(2, "0")} Out=0x${gpio.output.toString(16).padStart(2, "0")} In=0x${gpio.input.toString(16).padStart(2, "0")}`;
}

function setGpioStatus(text, ok = true) {
  gpioStatus.textContent = text;
  gpioStatus.className = `hint gpio-status ${ok ? "ok" : "err"}`;
}

async function setGpio(enable, output, label = "") {
  setGpioStatus(`${label || "Sende"} …`, true);
  try {
    const gpio = await api("/api/gpio", {
      method: "PATCH",
      body: JSON.stringify({ enable, output }),
    });
    if (state) state.gpio = gpio;
    renderGpio(gpio, false);
    setGpioStatus(`${label || "GPIO"} → ${formatGpio(gpio)}`, true);
  } catch (err) {
    console.error(err);
    setGpioStatus(err.message || String(err), false);
  }
}

function renderGpio(gpio, resetButtons = true) {
  if (!gpio) {
    gpioButtonsBuilt = false;
    gpioPanel.innerHTML = "";
    gpioPanel.textContent = "GPIO nicht verfügbar (kein Sonix-Chipset).";
    return;
  }

  let info = gpioPanel.querySelector(".gpio-info");
  if (!info || resetButtons) {
    gpioPanel.innerHTML = "";
    gpioButtonsBuilt = false;
    info = document.createElement("code");
    info.className = "gpio-info";
    gpioPanel.appendChild(info);
  }
  info.textContent = formatGpio(gpio);

  if (gpioButtonsBuilt) return;
  gpioButtonsBuilt = true;

  const presets = [
    ["Aus", 0, 0],
    ["GPIO0", 1, 1],
    ["GPIO1", 1, 2],
    ["GPIO2", 1, 4],
    ["Alle 3 LEDs", 7, 7],
    ["Enable+Out max", 255, 255],
  ];
  for (const [label, en, out] of presets) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = label;
    btn.addEventListener("click", () => setGpio(en, out, label));
    gpioPanel.appendChild(btn);
  }
}

function renderXuControls(controls) {
  xuControls.innerHTML = "";
  if (!controls?.length) {
    xuControls.textContent = "Keine Extension-Controls gefunden.";
    return;
  }

  for (const ctrl of controls) {
    const card = document.createElement("div");
    card.className = "xu-card";

    const title = document.createElement("h3");
    title.textContent = `${ctrl.label} (${ctrl.id})`;
    card.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "xu-meta";
    meta.textContent = `${ctrl.size} Byte · ${ctrl.protocol} · ${ctrl.value_hex}`;
    card.appendChild(meta);

    if (ctrl.writable && ctrl.size <= 16) {
      const bytesWrap = document.createElement("div");
      bytesWrap.className = "xu-bytes";
      const inputs = [];

      ctrl.value_bytes.forEach((val, idx) => {
        const wrap = document.createElement("div");
        wrap.className = "xu-byte";
        const lbl = document.createElement("label");
        lbl.textContent = `B${idx}`;
        const input = document.createElement("input");
        input.type = "number";
        input.min = 0;
        input.max = 255;
        input.value = val;
        input.addEventListener("change", async () => {
          const next = inputs.map((el) => Number(el.value) & 255);
          try {
            await setXuControl(ctrl, next);
          } catch (err) {
            console.error(err);
            await refresh(false);
          }
        });
        wrap.appendChild(lbl);
        wrap.appendChild(input);
        bytesWrap.appendChild(wrap);
        inputs.push(input);
      });
      card.appendChild(bytesWrap);
    }

    xuControls.appendChild(card);
  }
}

function updateRtspUi(stream) {
  const active = stream.rtsp_active;
  rtspToggle.textContent = active ? "RTSP stoppen" : "RTSP starten";
  rtspToggle.classList.toggle("active", active);
  rtspUrl.textContent = active ? stream.rtsp_public_url : "";
}

async function refresh(reloadVideo = true) {
  if (reloadVideo) startPreview();
  state = await api("/api/camera");
  renderDeviceSelect(state.devices, state.info.device);
  renderDeviceInfo(state);
  renderFormats(state.formats, state.stream);
  renderControls(state.controls);
  renderGpio(state.gpio);
  renderXuControls(state.xu_controls);
  updateRtspUi(state.stream);
}

deviceSelect.addEventListener("change", async () => {
  const device = deviceSelect.value;
  if (!device || device === state?.info?.device) return;
  gpioButtonsBuilt = false;
  preview.src = "";
  try {
    state = await api("/api/device", {
      method: "POST",
      body: JSON.stringify({ device }),
    });
    renderDeviceSelect(state.devices, state.info.device);
    renderDeviceInfo(state);
    renderFormats(state.formats, state.stream);
    renderControls(state.controls);
    renderGpio(state.gpio);
    renderXuControls(state.xu_controls);
    updateRtspUi(state.stream);
    reloadPreview();
  } catch (err) {
    console.error(err);
    await refresh(false);
  }
});

formatSelect.addEventListener("change", async () => {
  const fmt = JSON.parse(formatSelect.value);
  await api("/api/format", { method: "POST", body: JSON.stringify(fmt) });
  await refresh(false);
});

xuRescan.addEventListener("click", async () => {
  await api("/api/xu/rescan", { method: "POST" });
  await refresh(false);
});

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
