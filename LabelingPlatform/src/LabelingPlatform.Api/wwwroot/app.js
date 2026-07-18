"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";

// ---------------------------------------------------------------------------
// Stato
// ---------------------------------------------------------------------------
const state = {
  documents: [],
  taxonomy: null,       // { version, classes: [{id, layer}] }
  current: null,        // documento aperto
  pageIndex: 0,
  annotations: [],      // annotazioni della pagina corrente
  selectedId: null,
  tool: "pan",          // pan | bbox | poly
  zoom: 1,
  panX: 0,
  panY: 0,
  drawing: null,        // stato del disegno in corso
  hover: null,          // { raw, snapped } cursore in modalità disegno
  snap: {
    lines: true,        // calamita sui tratti scuri del disegno
    angle: true,        // aggancio a 0°/45°/90° (solo poligono)
    alt: false,         // Alt premuto = snap sospeso
    data: null,         // luminanza pagina (Uint8Array, ridotta)
    w: 0, h: 0, scale: 1,
  },
};

const LAYER_LABELS = {
  source_region: "Regioni della tavola",
  geometry: "Geometria",
  text: "Testi",
  symbol: "Simboli",
  architectural_candidate: "Architettura (candidati)",
  measurement: "Misure",
};

const $ = (id) => document.getElementById(id);

const viewList = $("view-list");
const viewDoc = $("view-doc");
const dropzone = $("dropzone");
const fileInput = $("file-input");
const uploadStatus = $("upload-status");
const docGrid = $("doc-grid");
const emptyHint = $("empty-hint");
const pageList = $("page-list");
const stage = $("stage");
const canvas = $("canvas");
const pageImage = $("page-image");
const overlay = $("overlay");
const zoomLevel = $("zoom-level");
const docTitle = $("doc-title");
const classSelect = $("class-select");
const toolHint = $("tool-hint");
const annoList = $("anno-list");
const annoCount = $("anno-count");
const annoEmpty = $("anno-empty");

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
async function apiJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error || body?.detail || `${url} → HTTP ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

const api = {
  documents: () => apiJson("/api/documents"),
  taxonomy: () => apiJson("/api/taxonomy"),
  annotations: (pageId) => apiJson(`/api/pages/${pageId}/annotations`),
  createAnnotation: (pageId, payload) => apiJson(`/api/pages/${pageId}/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }),
  updateAnnotation: (id, payload) => apiJson(`/api/annotations/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }),
  deleteAnnotation: (id) => apiJson(`/api/annotations/${id}`, { method: "DELETE" }),
};

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------
async function uploadFile(file) {
  const item = document.createElement("li");
  item.innerHTML = `<span>${escapeHtml(file.name)}</span><span class="st-run">caricamento…</span>`;
  uploadStatus.prepend(item);
  const badge = item.querySelector("span:last-child");

  try {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/documents", { method: "POST", body: form });
    const body = await res.json().catch(() => null);

    if (res.status === 201) {
      badge.textContent = `ok · ${body.pageCount} pagine`;
      badge.className = "st-ok";
    } else if (res.status === 200) {
      badge.textContent = "già presente (stesso contenuto)";
      badge.className = "st-ok";
    } else {
      badge.textContent = body?.detail || body?.error || `errore ${res.status}`;
      badge.className = "st-err";
    }
  } catch (err) {
    badge.textContent = `errore di rete: ${err.message}`;
    badge.className = "st-err";
  }
}

async function uploadFiles(files) {
  for (const file of files) await uploadFile(file);
  await refreshDocuments();
}

// ---------------------------------------------------------------------------
// Lista documenti
// ---------------------------------------------------------------------------
async function refreshDocuments() {
  state.documents = await api.documents();
  renderDocuments();
}

function renderDocuments() {
  docGrid.innerHTML = "";
  emptyHint.hidden = state.documents.length > 0;

  for (const doc of state.documents) {
    const firstPage = doc.pages[0];
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      ${firstPage
        ? `<img class="thumb" loading="lazy" src="/api/pages/${firstPage.id}/thumbnail" alt="">`
        : `<div class="thumb"></div>`}
      <div class="meta">
        <div class="name" title="${escapeHtml(doc.fileName)}">${escapeHtml(doc.fileName)}</div>
        <div class="info">${doc.sourceKind.toUpperCase()} · ${doc.pageCount} pag. · ${formatBytes(doc.sizeBytes)}</div>
      </div>`;
    card.addEventListener("click", () => openDocument(doc));
    docGrid.appendChild(card);
  }
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Tassonomia
// ---------------------------------------------------------------------------
function populateClassSelect() {
  classSelect.innerHTML = "";
  if (!state.taxonomy) return;

  const byLayer = new Map();
  for (const cls of state.taxonomy.classes) {
    if (!byLayer.has(cls.layer)) byLayer.set(cls.layer, []);
    byLayer.get(cls.layer).push(cls.id);
  }

  for (const [layer, ids] of byLayer) {
    const group = document.createElement("optgroup");
    group.label = LAYER_LABELS[layer] || layer;
    for (const id of ids) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = id;
      group.appendChild(opt);
    }
    classSelect.appendChild(group);
  }

  const preferred = state.taxonomy.classes.find((c) => c.id === "room_region");
  if (preferred) classSelect.value = preferred.id;
}

function classColor(classId) {
  let hash = 0;
  for (let i = 0; i < classId.length; i++)
    hash = (hash * 31 + classId.charCodeAt(i)) >>> 0;
  return `hsl(${hash % 360}, 72%, 55%)`;
}

// ---------------------------------------------------------------------------
// Viewer / editor
// ---------------------------------------------------------------------------
function openDocument(doc) {
  state.current = doc;
  state.pageIndex = 0;
  docTitle.textContent = doc.fileName;
  viewList.hidden = true;
  viewDoc.hidden = false;
  renderPageList();
  loadCurrentPage();
}

function closeDocument() {
  cancelDrawing();
  state.current = null;
  state.annotations = [];
  state.selectedId = null;
  viewDoc.hidden = true;
  viewList.hidden = false;
}

function currentPage() {
  return state.current?.pages[state.pageIndex] ?? null;
}

function renderPageList() {
  pageList.innerHTML = "";
  state.current.pages.forEach((page, index) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "page-thumb" + (index === state.pageIndex ? " active" : "");
    btn.innerHTML = `
      <img loading="lazy" src="/api/pages/${page.id}/thumbnail" alt="">
      <span class="page-no">pag. ${page.pageNumber}</span>`;
    btn.addEventListener("click", () => {
      if (index === state.pageIndex) return;
      cancelDrawing();
      state.pageIndex = index;
      renderPageList();
      loadCurrentPage();
    });
    pageList.appendChild(btn);
  });
}

async function loadCurrentPage() {
  const page = currentPage();
  if (!page) return;

  state.annotations = [];
  state.selectedId = null;
  renderOverlay();
  renderAnnotationPanel();

  pageImage.onload = () => {
    overlay.setAttribute("width", pageImage.naturalWidth);
    overlay.setAttribute("height", pageImage.naturalHeight);
    overlay.setAttribute("viewBox", `0 0 ${pageImage.naturalWidth} ${pageImage.naturalHeight}`);
    fitToStage();
    buildSnapData();
  };
  pageImage.src = `/api/pages/${page.id}/image`;

  try {
    state.annotations = await api.annotations(page.id);
  } catch (err) {
    console.error(err);
    state.annotations = [];
  }
  renderOverlay();
  renderAnnotationPanel();
}

// --- trasformazioni ---------------------------------------------------------
function applyTransform() {
  canvas.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
  zoomLevel.textContent = `${Math.round(state.zoom * 100)}%`;
  // gli spessori delle forme sono in unità immagine: compensali con lo zoom
  // così a schermo restano costanti (il vector-effect SVG non copre i transform CSS)
  const z = state.zoom;
  overlay.style.setProperty("--sw", `${2 / z}px`);
  overlay.style.setProperty("--sw-sel", `${3 / z}px`);
  overlay.style.setProperty("--sw-thin", `${1.5 / z}px`);
  overlay.style.setProperty("--dash", `${6 / z}px ${4 / z}px`);
}

function fitToStage() {
  const rect = stage.getBoundingClientRect();
  const w = pageImage.naturalWidth;
  const h = pageImage.naturalHeight;
  if (!w || !h) return;
  state.zoom = Math.min(rect.width / w, rect.height / h) * 0.97;
  state.panX = (rect.width - w * state.zoom) / 2;
  state.panY = (rect.height - h * state.zoom) / 2;
  applyTransform();
}

function toImg(clientX, clientY) {
  const rect = stage.getBoundingClientRect();
  return {
    x: (clientX - rect.left - state.panX) / state.zoom,
    y: (clientY - rect.top - state.panY) / state.zoom,
  };
}

function zoomAt(clientX, clientY, factor) {
  const rect = stage.getBoundingClientRect();
  const mx = clientX - rect.left;
  const my = clientY - rect.top;
  const nextZoom = Math.min(12, Math.max(0.03, state.zoom * factor));
  const ratio = nextZoom / state.zoom;
  state.panX = mx - (mx - state.panX) * ratio;
  state.panY = my - (my - state.panY) * ratio;
  state.zoom = nextZoom;
  applyTransform();
  // i pallini dei vertici e l'anello di snap hanno raggio in unità immagine:
  // vanno ridisegnati con il nuovo zoom
  if (state.drawing || state.hover) renderOverlay();
}

function zoomCenter(factor) {
  const rect = stage.getBoundingClientRect();
  zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, factor);
}

// --- snapping ---------------------------------------------------------------
// Le planimetrie sono inchiostro scuro su carta chiara: la calamita cerca nel
// raggio del cursore il pixel di "inchiostro" migliore (scuro e vicino).
function buildSnapData() {
  state.snap.data = null;
  try {
    const w = pageImage.naturalWidth;
    const h = pageImage.naturalHeight;
    if (!w || !h) return;
    const scale = Math.min(1, 2600 / Math.max(w, h));
    const sw = Math.max(1, Math.round(w * scale));
    const sh = Math.max(1, Math.round(h * scale));
    const cv = document.createElement("canvas");
    cv.width = sw;
    cv.height = sh;
    const ctx = cv.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(pageImage, 0, 0, sw, sh);
    const rgba = ctx.getImageData(0, 0, sw, sh).data;
    const lum = new Uint8Array(sw * sh);
    for (let i = 0, j = 0; i < lum.length; i++, j += 4)
      lum[i] = (rgba[j] * 3 + rgba[j + 1] * 6 + rgba[j + 2]) / 10;
    state.snap.data = lum;
    state.snap.w = sw;
    state.snap.h = sh;
    state.snap.scale = scale;
  } catch (err) {
    console.warn("Snap non disponibile su questa pagina:", err);
  }
}

function snapToInk(p) {
  const s = state.snap;
  if (!s.data) return p;
  const radiusImg = Math.max(3, Math.min(25, 12 / state.zoom)); // ~12 px schermo
  const sc = s.scale;
  const cx = Math.round(p.x * sc);
  const cy = Math.round(p.y * sc);
  const r = Math.max(1, Math.round(radiusImg * sc));
  let best = null;
  let bestScore = Infinity;
  for (let dy = -r; dy <= r; dy++) {
    const y = cy + dy;
    if (y < 0 || y >= s.h) continue;
    for (let dx = -r; dx <= r; dx++) {
      const x = cx + dx;
      if (x < 0 || x >= s.w) continue;
      const lum = s.data[y * s.w + x];
      if (lum > 170) continue; // non è inchiostro
      const dist = Math.hypot(dx, dy);
      if (dist > r) continue;
      const score = lum * 0.6 + (dist / r) * 140;
      if (score < bestScore) {
        bestScore = score;
        best = { x: (x + 0.5) / sc, y: (y + 0.5) / sc };
      }
    }
  }
  return best ?? p;
}

function snapToAxis(p, prev) {
  if (!prev) return p;
  const dx = p.x - prev.x;
  const dy = p.y - prev.y;
  const len = Math.hypot(dx, dy);
  if (len < 4) return p;
  const step = Math.PI / 4; // 0°, 45°, 90°…
  const angle = Math.atan2(dy, dx);
  const target = Math.round(angle / step) * step;
  if (Math.abs(angle - target) > 8 * Math.PI / 180) return p;
  return { x: prev.x + len * Math.cos(target), y: prev.y + len * Math.sin(target) };
}

/// Snap completo del punto: calamita inchiostro + eventuale aggancio angolare.
function snapDraw(raw, prevVertex, useAngle) {
  if (state.snap.alt) return raw;
  let p = state.snap.lines ? snapToInk(raw) : raw;
  if (useAngle && state.snap.angle) p = snapToAxis(p, prevVertex);
  return p;
}

// --- overlay SVG ------------------------------------------------------------
function renderOverlay() {
  overlay.innerHTML = "";
  overlay.classList.toggle("no-pick", state.tool !== "pan");

  for (const anno of state.annotations) {
    const color = classColor(anno.classId);
    const shape = buildShape(anno.geometryType, anno.points);
    if (!shape) continue;
    shape.classList.add("shape");
    if (anno.id === state.selectedId) shape.classList.add("selected");
    shape.setAttribute("stroke", color);
    shape.setAttribute("fill", color);
    shape.setAttribute("fill-opacity", "0.13");
    shape.addEventListener("pointerdown", (e) => {
      if (state.tool !== "pan") return;
      e.stopPropagation();
      selectAnnotation(anno.id);
    });
    overlay.appendChild(shape);
  }

  renderDrawingPreview();
  renderSnapIndicator();
}

function buildShape(geometryType, points) {
  if (geometryType === "bbox" && points.length === 2) {
    const [a, b] = points;
    const rect = document.createElementNS(SVG_NS, "rect");
    rect.setAttribute("x", Math.min(a.x, b.x));
    rect.setAttribute("y", Math.min(a.y, b.y));
    rect.setAttribute("width", Math.abs(b.x - a.x));
    rect.setAttribute("height", Math.abs(b.y - a.y));
    return rect;
  }
  if (geometryType === "polygon" && points.length >= 3) {
    const poly = document.createElementNS(SVG_NS, "polygon");
    poly.setAttribute("points", points.map((p) => `${p.x},${p.y}`).join(" "));
    return poly;
  }
  return null;
}

function renderDrawingPreview() {
  const d = state.drawing;
  if (!d) return;
  const color = classColor(classSelect.value || "unknown");

  if (d.type === "bbox" && d.start && d.end) {
    const rect = document.createElementNS(SVG_NS, "rect");
    rect.setAttribute("x", Math.min(d.start.x, d.end.x));
    rect.setAttribute("y", Math.min(d.start.y, d.end.y));
    rect.setAttribute("width", Math.abs(d.end.x - d.start.x));
    rect.setAttribute("height", Math.abs(d.end.y - d.start.y));
    styleTemp(rect, color);
    overlay.appendChild(rect);
  }

  if (d.type === "poly" && d.points.length > 0) {
    const preview = [...d.points, ...(d.cursor ? [d.cursor] : [])];
    const line = document.createElementNS(SVG_NS, "polyline");
    line.setAttribute("points", preview.map((p) => `${p.x},${p.y}`).join(" "));
    styleTemp(line, color);
    line.setAttribute("fill", "none");
    overlay.appendChild(line);

    const nearFirst = d.points.length >= 3 && d.cursor && isNearFirstVertex(d.cursor);
    d.points.forEach((p, index) => {
      const isFirst = index === 0;
      const dot = document.createElementNS(SVG_NS, "circle");
      dot.classList.add("vtx");
      dot.setAttribute("cx", p.x);
      dot.setAttribute("cy", p.y);
      dot.setAttribute("r", (isFirst && nearFirst ? 8 : isFirst ? 6 : 4) / state.zoom);
      dot.setAttribute("fill", isFirst && nearFirst ? "#39d98a" : color);
      if (isFirst) dot.setAttribute("stroke", "#fff");
      overlay.appendChild(dot);
    });
  }
}

function isNearFirstVertex(p) {
  const d = state.drawing;
  if (!d || d.type !== "poly" || d.points.length === 0) return false;
  const first = d.points[0];
  return Math.hypot(p.x - first.x, p.y - first.y) < 12 / state.zoom;
}

function renderSnapIndicator() {
  if (state.tool === "pan" || !state.hover) return;
  const { raw, snapped } = state.hover;
  const engaged = Math.hypot(snapped.x - raw.x, snapped.y - raw.y) > 0.75;
  const ring = document.createElementNS(SVG_NS, "circle");
  ring.classList.add("snap-ring");
  ring.setAttribute("cx", snapped.x);
  ring.setAttribute("cy", snapped.y);
  ring.setAttribute("r", 6 / state.zoom);
  ring.setAttribute("fill", "none");
  ring.setAttribute("stroke", engaged ? "#39d98a" : "#8aa0b8");
  ring.setAttribute("pointer-events", "none");
  overlay.appendChild(ring);
}

function styleTemp(el, color) {
  el.classList.add("temp");
  el.setAttribute("stroke", color);
  el.setAttribute("fill", color);
  el.setAttribute("fill-opacity", "0.08");
  el.setAttribute("pointer-events", "none");
}

// --- pannello annotazioni ---------------------------------------------------
function renderAnnotationPanel() {
  annoList.innerHTML = "";
  annoCount.textContent = state.annotations.length ? `(${state.annotations.length})` : "";
  annoEmpty.hidden = state.annotations.length > 0;

  for (const anno of state.annotations) {
    const row = document.createElement("div");
    row.className = "anno-row" + (anno.id === state.selectedId ? " selected" : "");
    row.dataset.id = anno.id;

    const head = document.createElement("div");
    head.className = "row-head";

    const dot = document.createElement("span");
    dot.className = "dot";
    dot.style.background = classColor(anno.classId);

    const cls = document.createElement("select");
    cls.className = "cls";
    for (const c of state.taxonomy?.classes ?? []) {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.id;
      cls.appendChild(opt);
    }
    cls.value = anno.classId;
    cls.addEventListener("change", () => saveAnnotationEdit(anno, { classId: cls.value }));

    const geom = document.createElement("span");
    geom.className = "geom";
    geom.textContent = anno.geometryType === "bbox" ? "▭" : "⬠";

    head.append(dot, cls, geom);

    const note = document.createElement("input");
    note.className = "note";
    note.placeholder = "nota…";
    note.value = anno.note || "";
    note.addEventListener("change", () => saveAnnotationEdit(anno, { note: note.value }));

    const actions = document.createElement("div");
    actions.className = "row-actions";

    const cropBtn = document.createElement("button");
    cropBtn.type = "button";
    cropBtn.textContent = "pezzetto";
    cropBtn.title = "Scarica il ritaglio PNG";
    cropBtn.addEventListener("click", () => window.open(`/api/annotations/${anno.id}/crop`, "_blank"));

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "danger";
    delBtn.textContent = "elimina";
    delBtn.addEventListener("click", () => removeAnnotation(anno.id));

    actions.append(cropBtn, delBtn);
    row.append(head, note, actions);
    row.addEventListener("click", (e) => {
      if (e.target === cls || e.target === note || e.target.tagName === "BUTTON") return;
      selectAnnotation(anno.id);
    });
    annoList.appendChild(row);
  }
}

function selectAnnotation(id) {
  state.selectedId = state.selectedId === id ? null : id;
  renderOverlay();
  renderAnnotationPanel();
  const row = annoList.querySelector(`[data-id="${state.selectedId}"]`);
  row?.scrollIntoView({ block: "nearest" });
}

async function saveAnnotationEdit(anno, changes) {
  const payload = {
    classId: changes.classId ?? anno.classId,
    geometryType: anno.geometryType,
    points: anno.points,
    note: changes.note ?? anno.note,
  };
  try {
    const updated = await api.updateAnnotation(anno.id, payload);
    const index = state.annotations.findIndex((a) => a.id === anno.id);
    if (index >= 0) state.annotations[index] = updated;
    renderOverlay();
    renderAnnotationPanel();
  } catch (err) {
    alert(`Salvataggio fallito: ${err.message}`);
  }
}

async function removeAnnotation(id) {
  try {
    await api.deleteAnnotation(id);
    state.annotations = state.annotations.filter((a) => a.id !== id);
    if (state.selectedId === id) state.selectedId = null;
    renderOverlay();
    renderAnnotationPanel();
  } catch (err) {
    alert(`Eliminazione fallita: ${err.message}`);
  }
}

async function persistNewAnnotation(geometryType, points) {
  const page = currentPage();
  if (!page) return;
  try {
    const created = await api.createAnnotation(page.id, {
      classId: classSelect.value,
      geometryType,
      points,
      note: "",
    });
    state.annotations.push(created);
    state.selectedId = created.id;
    renderOverlay();
    renderAnnotationPanel();
  } catch (err) {
    alert(`Creazione annotazione fallita: ${err.message}`);
  }
}

// --- strumenti --------------------------------------------------------------
function setTool(tool) {
  cancelDrawing();
  state.tool = tool;
  state.hover = null;
  for (const [id, name] of [["tool-pan", "pan"], ["tool-bbox", "bbox"], ["tool-poly", "poly"]])
    $(id).classList.toggle("active", name === tool);
  stage.classList.toggle("drawing", tool !== "pan");
  overlay.classList.toggle("no-pick", tool !== "pan");
  updateToolHint();
}

function updateToolHint() {
  const tool = state.tool;
  const drawingPoly = state.drawing?.type === "poly";
  toolHint.hidden = tool === "pan";
  $("tool-hint-text").textContent =
    tool === "bbox"
      ? "Rettangolo: trascina sull'area da annotare. 🧲 aggancia ai tratti (Alt sospende). Rotella premuta o Spazio = sposta la vista."
      : tool === "poly"
        ? (drawingPoly
            ? "Chiudi cliccando sul primo punto (si illumina), doppio click, Invio o il bottone a destra. Rotella premuta o Spazio = spostati senza perdere i vertici."
            : "Poligono: un click per ogni vertice. 🧲 aggancia ai tratti, 📐 raddrizza a 0°/45°/90° (Alt sospende). Rotella premuta o Spazio = sposta la vista.")
        : "";
  $("poly-finish").hidden = !(drawingPoly && state.drawing.points.length >= 3);
  $("draw-cancel").hidden = !state.drawing;
}

function cancelDrawing() {
  state.drawing = null;
  state.hover = null;
  renderOverlay();
  if (state.current) updateToolHint();
}

// --- interazioni sullo stage ------------------------------------------------
let panSession = null;
let spaceHeld = false;
let lastClient = null;

function finalizeBbox() {
  const d = state.drawing;
  if (!d || d.type !== "bbox") return;
  state.drawing = null;
  updateToolHint();
  const w = Math.abs(d.end.x - d.start.x);
  const h = Math.abs(d.end.y - d.start.y);
  if (w > 3 && h > 3) {
    persistNewAnnotation("bbox", [
      { x: Math.min(d.start.x, d.end.x), y: Math.min(d.start.y, d.end.y) },
      { x: Math.max(d.start.x, d.end.x), y: Math.max(d.start.y, d.end.y) },
    ]);
  }
  renderOverlay();
}

// il click centrale su Windows attiva l'autoscroll del browser e ruba il
// gesto di pan: va bloccato su mousedown (pointerdown non basta)
stage.addEventListener("mousedown", (e) => {
  if (e.button === 1) e.preventDefault();
});
stage.addEventListener("auxclick", (e) => {
  if (e.button === 1) e.preventDefault();
});

stage.addEventListener("pointerdown", (e) => {
  lastClient = { x: e.clientX, y: e.clientY };

  if (e.button === 1) {
    // rotella premuta = pan, SEMPRE: anche a metà di un disegno.
    // Lo spostamento vero è gestito in pointermove leggendo e.buttons,
    // perché se il sinistro è già premuto il browser non emette pointerdown.
    stage.classList.add("panning");
    stage.setPointerCapture(e.pointerId);
    e.preventDefault();
    return;
  }

  if (e.button !== 0) return;

  if (spaceHeld || state.tool === "pan") {
    panSession = { x: e.clientX, y: e.clientY, moved: false };
    stage.classList.add("panning");
    stage.setPointerCapture(e.pointerId);
    return;
  }

  if (state.tool === "bbox") {
    const raw = toImg(e.clientX, e.clientY);
    const p = snapDraw(raw, null, false);
    state.drawing = { type: "bbox", start: p, end: p };
    stage.setPointerCapture(e.pointerId);
    updateToolHint();
    renderOverlay();
  }
});

stage.addEventListener("pointermove", (e) => {
  const prevClient = lastClient ?? { x: e.clientX, y: e.clientY };
  lastClient = { x: e.clientX, y: e.clientY };

  const middlePan = (e.buttons & 4) !== 0;
  if (middlePan) {
    // rotella giù: panna anche se il sinistro sta disegnando un rettangolo
    state.panX += e.clientX - prevClient.x;
    state.panY += e.clientY - prevClient.y;
    if (panSession) {
      panSession.x = e.clientX;
      panSession.y = e.clientY;
    }
    stage.classList.add("panning");
    applyTransform();
  } else if (panSession) {
    state.panX += e.clientX - panSession.x;
    state.panY += e.clientY - panSession.y;
    panSession = { x: e.clientX, y: e.clientY, moved: true };
    applyTransform();
    return;
  } else {
    stage.classList.remove("panning");
  }

  if (state.tool === "pan") return;

  // sinistro rilasciato durante l'accordo con la rotella: il browser non
  // emette pointerup finché un bottone resta premuto, quindi chiudi qui
  if (state.drawing?.type === "bbox" && (e.buttons & 1) === 0) {
    finalizeBbox();
    return;
  }

  const raw = toImg(e.clientX, e.clientY);
  const prevVertex = state.drawing?.type === "poly"
    ? state.drawing.points[state.drawing.points.length - 1]
    : null;
  const snapped = snapDraw(raw, prevVertex, state.tool === "poly");
  state.hover = { raw, snapped };

  if (state.drawing?.type === "bbox") {
    state.drawing.end = snapped;
  } else if (state.drawing?.type === "poly") {
    // vicino al primo vertice il cursore ci si aggancia per chiudere
    state.drawing.cursor = isNearFirstVertex(raw) ? state.drawing.points[0] : snapped;
  }
  renderOverlay();
});

stage.addEventListener("pointerup", (e) => {
  lastClient = { x: e.clientX, y: e.clientY };

  if (e.button === 1) {
    // rilascio della rotella: se non c'è altro pan attivo, torna normale
    if (!panSession) stage.classList.remove("panning");
    // se il sinistro era già stato rilasciato durante l'accordo, chiudi il rettangolo
    if (state.drawing?.type === "bbox" && (e.buttons & 1) === 0) finalizeBbox();
    return;
  }

  if (panSession) {
    stage.classList.remove("panning");
    stage.releasePointerCapture(e.pointerId);
    panSession = null;
    return;
  }

  if (state.drawing?.type === "bbox") {
    finalizeBbox();
    return;
  }

  if (state.tool === "poly" && e.button === 0) {
    const raw = toImg(e.clientX, e.clientY);

    // click sul primo vertice = chiusura
    if (state.drawing?.points.length >= 3 && isNearFirstVertex(raw)) {
      finishPolygon();
      return;
    }

    const prevVertex = state.drawing?.points[state.drawing.points.length - 1] ?? null;
    const p = snapDraw(raw, prevVertex, true);
    if (!state.drawing) state.drawing = { type: "poly", points: [], cursor: null };
    state.drawing.points.push(p);
    updateToolHint();
    renderOverlay();
  }
});

stage.addEventListener("dblclick", (e) => {
  if (state.tool === "poly" && state.drawing?.points.length >= 3) {
    e.preventDefault();
    finishPolygon();
    return;
  }
  if (state.tool === "pan") fitToStage();
});

function finishPolygon() {
  const d = state.drawing;
  if (!d || d.points.length < 3) return;
  // il doppio click genera due click sullo stesso punto: rimuovi il duplicato finale
  const pts = d.points;
  const last = pts[pts.length - 1];
  const prev = pts[pts.length - 2];
  if (pts.length > 3 && Math.hypot(last.x - prev.x, last.y - prev.y) < 2 / state.zoom)
    pts.pop();
  state.drawing = null;
  updateToolHint();
  persistNewAnnotation("polygon", pts);
}

stage.addEventListener("wheel", (e) => {
  e.preventDefault();
  zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.15 : 1 / 1.15);
}, { passive: false });

// --- toolbar e tastiera -----------------------------------------------------
$("back").addEventListener("click", closeDocument);
$("zoom-in").addEventListener("click", () => zoomCenter(1.25));
$("zoom-out").addEventListener("click", () => zoomCenter(1 / 1.25));
$("zoom-fit").addEventListener("click", fitToStage);
$("tool-pan").addEventListener("click", () => setTool("pan"));
$("tool-bbox").addEventListener("click", () => setTool("bbox"));
$("tool-poly").addEventListener("click", () => setTool("poly"));
$("poly-finish").addEventListener("click", finishPolygon);
$("draw-cancel").addEventListener("click", cancelDrawing);
$("snap-lines").addEventListener("click", () => {
  state.snap.lines = !state.snap.lines;
  $("snap-lines").classList.toggle("active", state.snap.lines);
});
$("snap-angle").addEventListener("click", () => {
  state.snap.angle = !state.snap.angle;
  $("snap-angle").classList.toggle("active", state.snap.angle);
});

document.addEventListener("keydown", (e) => {
  if (viewDoc.hidden || !state.current) return;

  if (e.key === "Alt") {
    state.snap.alt = true;
    e.preventDefault(); // evita il focus sul menu del browser
    return;
  }

  const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName);
  if (typing) return;

  if (e.key === " ") {
    if (!spaceHeld) {
      spaceHeld = true;
      stage.classList.remove("drawing");
    }
    e.preventDefault(); // niente scroll della pagina
    return;
  }

  if (e.key === "Escape") {
    if (state.drawing) cancelDrawing();
    else if (state.tool !== "pan") setTool("pan");
    else closeDocument();
  }
  if (e.key === "Enter" && state.tool === "poly") finishPolygon();
  if (e.key === "1") setTool("pan");
  if (e.key === "2") setTool("bbox");
  if (e.key === "3") setTool("poly");
  if ((e.key === "Delete" || e.key === "Backspace") && state.selectedId)
    removeAnnotation(state.selectedId);
  if (e.key === "ArrowDown" || e.key === "PageDown") changePage(1);
  if (e.key === "ArrowUp" || e.key === "PageUp") changePage(-1);
});

function changePage(delta) {
  const next = state.pageIndex + delta;
  if (next < 0 || next >= state.current.pages.length) return;
  cancelDrawing();
  state.pageIndex = next;
  renderPageList();
  loadCurrentPage();
}

document.addEventListener("keyup", (e) => {
  if (e.key === "Alt") state.snap.alt = false;
  if (e.key === " ") {
    spaceHeld = false;
    stage.classList.toggle("drawing", state.tool !== "pan");
  }
});
window.addEventListener("blur", () => {
  state.snap.alt = false;
  spaceHeld = false;
  if (state.current) stage.classList.toggle("drawing", state.tool !== "pan");
});

window.addEventListener("resize", () => {
  if (!viewDoc.hidden && state.current) fitToStage();
});

// --- upload UI --------------------------------------------------------------
$("pick-files").addEventListener("click", () => fileInput.click());
dropzone.addEventListener("click", (e) => {
  if (e.target === dropzone || e.target.classList.contains("dz-title")) fileInput.click();
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) uploadFiles([...fileInput.files]);
  fileInput.value = "";
});

["dragenter", "dragover"].forEach((type) =>
  dropzone.addEventListener(type, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  }));
["dragleave", "drop"].forEach((type) =>
  dropzone.addEventListener(type, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
  }));
dropzone.addEventListener("drop", (e) => {
  if (e.dataTransfer?.files?.length) uploadFiles([...e.dataTransfer.files]);
});

// ---------------------------------------------------------------------------
// Avvio
// ---------------------------------------------------------------------------
(async function start() {
  try {
    state.taxonomy = await api.taxonomy();
    populateClassSelect();
  } catch (err) {
    console.error("Tassonomia non disponibile:", err);
  }
  try {
    await refreshDocuments();
  } catch (err) {
    emptyHint.hidden = false;
    emptyHint.textContent = `Errore nel caricamento dei documenti: ${err.message}`;
  }
})();
