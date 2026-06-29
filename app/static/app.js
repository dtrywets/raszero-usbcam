const preview = document.getElementById("preview");
const deviceInfo = document.getElementById("device-info");
const controlsForm = document.getElementById("controls-form");
const formatSelect = document.getElementById("format-select");
const rtspToggle = document.getElementById("rtsp-toggle");
const rtspUrl = document.getElementById("rtsp-url");
const xuControls = document.getElementById("xu-controls");
const xuRescan = document.getElementById("xu-rescan");

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
    title.textContent = ctrl.id;
    card.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "xu-meta";
    meta.textContent = `${ctrl.size} Byte · ${ctrl.writable ? "schreibbar" : "nur lesen"} · ${ctrl.value_hex}`;
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
        input.disabled = !ctrl.writable;
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

      if (ctrl.id === "u3_s2") {
        const actions = document.createElement("div");
        actions.className = "xu-actions";
        const offBtn = document.createElement("button");
        offBtn.type = "button";
        offBtn.textContent = "Leuchtring aus";
        offBtn.addEventListener("click", () =>
          setXuControl(ctrl, [0x3c, 0, 0, 0, 0x15, 0x16, 0x05, 0]),
        );
        const onBtn = document.createElement("button");
        onBtn.type = "button";
        onBtn.textContent = "Leuchtring an";
        onBtn.addEventListener("click", () =>
          setXuControl(ctrl, [0x3c, 0, 0x0c, 0x0c, 0x15, 0x16, 0x05, 0]),
        );
        actions.appendChild(offBtn);
        actions.appendChild(onBtn);
        card.appendChild(actions);
      }
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
  state = await api("/api/camera");
  renderDeviceInfo(state);
  renderFormats(state.formats, state.stream);
  renderControls(state.controls);
  renderXuControls(state.xu_controls);
  updateRtspUi(state.stream);
  if (reloadVideo) startPreview();
}

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
