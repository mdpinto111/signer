'use strict';

// ── Constants ─────────────────────────────────────────────────────────────────
const ZOOM = 1.5;
const GAP = 20;           // px between rendered pages on canvas
const DRAG_THRESHOLD = 6; // px — below this a drag is treated as a click
const PAGE_SHADOW = 8;    // canvas shadow blur
// Text is anchored at the top of the line; the baseline sits this many
// font-size units below it. Must match TEXT_ASCENT in main.py.
const TEXT_ASCENT = 0.8;

// ── State ─────────────────────────────────────────────────────────────────────
const S = {
  sessionId: null,
  pages: [],          // [{width, height, pdf_width, pdf_height, img}]
  sigImg: null,       // HTMLImageElement with transparent bg
  sigW: 120,
  sigH: 50,
  placements: [],     // [{type, page, cx, cy, w, h, text, size, color}]
  mode: 'signature',  // 'signature' | 'text'
  pageOffsets: [],    // canvas-y of top of each page
  dragStart: null,    // {x, y} canvas coords at mousedown
  mousePos: { x: -9999, y: -9999 },
  isDragging: false,
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const canvas       = document.getElementById('main-canvas');
const ctx          = canvas.getContext('2d');
const canvasWrap   = document.getElementById('canvas-wrap');
const dropHint     = document.getElementById('drop-hint');
const pdfInput     = document.getElementById('pdf-file-input');
const sigInput     = document.getElementById('sig-file-input');
const saveBtn      = document.getElementById('save-btn');
const undoBtn      = document.getElementById('undo-btn');
const sigSection   = document.getElementById('sig-section');
const textSection  = document.getElementById('text-section');
const sigFilename  = document.getElementById('sig-filename');
const sigPreview   = document.getElementById('sig-preview-img');
const sigW         = document.getElementById('sig-w');
const sigH         = document.getElementById('sig-h');
const textInput    = document.getElementById('text-input');
const fontSizeEl   = document.getElementById('font-size');
const fontColorEl  = document.getElementById('font-color');
const fontColorHex = document.getElementById('font-color-hex');
const placList     = document.getElementById('placements-list');
const loadingOv    = document.getElementById('loading-overlay');
const loadingTxt   = document.getElementById('loading-text');
const toastEl      = document.getElementById('toast');
const topFilename  = document.getElementById('topbar-filename');
const modeInputs   = document.querySelectorAll('input[name="mode"]');
const statusBar    = document.getElementById('statusbar');
const statusPages  = document.getElementById('status-pages');
const statusSig    = document.getElementById('status-sig');
const statusHint   = document.getElementById('status-hint');

// ── Utility ───────────────────────────────────────────────────────────────────

function isRTL(text) {
  for (const ch of text) {
    const cp = ch.codePointAt(0);
    if ((cp >= 0x0590 && cp <= 0x05FF) || (cp >= 0x0600 && cp <= 0x06FF)) return true;
  }
  return false;
}

function hexToRgba(hex, alpha = 1) {
  const h = hex.replace('#', '').padEnd(6, '0').slice(0, 6);
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function showLoading(msg = 'Processing…') {
  loadingTxt.textContent = msg;
  loadingOv.classList.add('visible');
}
function hideLoading() { loadingOv.classList.remove('visible'); }

let toastTimer;
function showToast(msg, type = '') {
  toastEl.textContent = msg;
  toastEl.className = 'show ' + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.className = ''; }, 3000);
}

// ── Coordinate helpers ────────────────────────────────────────────────────────

/** Return index of page whose rendered area contains canvas-y `cy`. */
function pageAtY(cy) {
  for (let i = 0; i < S.pageOffsets.length; i++) {
    const top = S.pageOffsets[i];
    const bot = top + S.pages[i].height;
    if (cy >= top && cy < bot) return i;
  }
  return S.pages.length - 1;
}

/** Canvas pixel coords → {page, x, y} in PDF points. */
function canvasToPdf(cx, cy) {
  const page = pageAtY(cy);
  const x = cx / ZOOM;
  const y = (cy - S.pageOffsets[page]) / ZOOM;
  return { page, x, y };
}

/** PDF point coords on page `pageIdx` → canvas pixel coords. */
function pdfToCanvas(pageIdx, px, py) {
  return {
    x: px * ZOOM,
    y: S.pageOffsets[pageIdx] + py * ZOOM,
  };
}

/** Get canvas coords relative to the canvas element from a mouse/touch event.
 *  Uses e.offsetX/Y which the browser computes natively relative to the target
 *  element — correct regardless of scroll position or flexbox centering. */
function eventToCanvas(e) {
  return { x: e.offsetX, y: e.offsetY };
}

// ── Canvas rendering ──────────────────────────────────────────────────────────

/** Draw text with its top-left (LTR) or top-right (RTL) corner at canvas (x, y).
 *  `size` is in PDF points, so it is scaled by ZOOM like the rendered page. */
function drawText(text, x, y, size, fillStyle) {
  const px = size * ZOOM;
  ctx.save();
  ctx.font         = `${Math.max(6, px)}px Arial, sans-serif`;
  ctx.fillStyle    = fillStyle;
  ctx.direction    = isRTL(text) ? 'rtl' : 'ltr';
  ctx.textAlign    = isRTL(text) ? 'right' : 'left';
  ctx.textBaseline = 'alphabetic';
  ctx.fillText(text, x, y + px * TEXT_ASCENT);
  ctx.restore();
}

function totalCanvasHeight() {
  if (!S.pages.length) return 0;
  const last = S.pages.length - 1;
  return S.pageOffsets[last] + S.pages[last].height;
}

function totalCanvasWidth() {
  return S.pages.reduce((m, p) => Math.max(m, p.width), 0);
}

function computePageOffsets() {
  S.pageOffsets = [];
  let y = 0;
  for (const p of S.pages) {
    S.pageOffsets.push(y);
    y += p.height + GAP;
  }
}

function drawFrame() {
  if (!S.pages.length) return;

  const W = totalCanvasWidth();
  const H = totalCanvasHeight();
  canvas.width  = W;
  canvas.height = H;

  ctx.clearRect(0, 0, W, H);

  // ── Draw pages ──
  for (let i = 0; i < S.pages.length; i++) {
    const p = S.pages[i];
    const y = S.pageOffsets[i];
    if (!p.img) continue;

    // Drop shadow
    ctx.save();
    ctx.shadowColor   = 'rgba(0,0,0,0.5)';
    ctx.shadowBlur    = PAGE_SHADOW;
    ctx.shadowOffsetY = 2;
    ctx.drawImage(p.img, 0, y, p.width, p.height);
    ctx.restore();
  }

  // ── Draw placements ──
  for (let i = 0; i < S.placements.length; i++) {
    const pl = S.placements[i];
    const cv = pdfToCanvas(pl.page, pl.cx, pl.cy);
    if (pl.type === 'signature') {
      if (S.sigImg) {
        const w = pl.w * ZOOM;
        const h = pl.h * ZOOM;
        ctx.globalAlpha = 0.9;
        ctx.drawImage(S.sigImg, cv.x, cv.y, w, h);
        ctx.globalAlpha = 1.0;
        // Dashed blue border
        ctx.save();
        ctx.strokeStyle = '#4f8ef7';
        ctx.lineWidth   = 1.5;
        ctx.setLineDash([5, 3]);
        ctx.strokeRect(cv.x, cv.y, w, h);
        ctx.restore();
        // Index label
        ctx.save();
        ctx.font         = 'bold 10px sans-serif';
        ctx.fillStyle    = '#4f8ef7';
        ctx.fillText(String(i + 1), cv.x + 3, cv.y + 11);
        ctx.restore();
      }
    } else {
      drawText(pl.text, cv.x, cv.y, pl.size, pl.color || '#000000');
    }
  }

  // ── Draw rubber-band ──
  if (S.isDragging && S.dragStart && S.mode === 'signature') {
    const x0 = S.dragStart.x, y0 = S.dragStart.y;
    const x1 = S.mousePos.x,  y1 = S.mousePos.y;
    const dx = Math.abs(x1 - x0), dy = Math.abs(y1 - y0);
    if (dx > DRAG_THRESHOLD || dy > DRAG_THRESHOLD) {
      ctx.save();
      ctx.strokeStyle = '#ff7043';
      ctx.lineWidth   = 2;
      ctx.setLineDash([6, 3]);
      ctx.strokeRect(
        Math.min(x0, x1), Math.min(y0, y1),
        Math.abs(x1 - x0), Math.abs(y1 - y0)
      );
      ctx.restore();
    }
  }

  // ── Draw ghost ──
  const mx = S.mousePos.x, my = S.mousePos.y;
  if (mx > -100 && !S.isDragging) {
    if (S.mode === 'signature' && S.sigImg) {
      const w = S.sigW * ZOOM;
      const h = S.sigH * ZOOM;
      ctx.globalAlpha = 0.45;
      ctx.drawImage(S.sigImg, mx, my, w, h);
      ctx.globalAlpha = 1.0;
    } else if (S.mode === 'text') {
      const text = textInput.value.trim();
      if (text) {
        const size = Math.max(4, parseFloat(fontSizeEl.value) || 12);
        drawText(text, mx, my, size, hexToRgba(fontColorEl.value, 0.45));
      }
    }
  }
}

// ── Status bar ────────────────────────────────────────────────────────────────

function updateStatusBar() {
  if (!S.pages.length) { statusBar.style.display = 'none'; return; }
  statusBar.style.display = 'flex';

  statusPages.className = 'ok';
  statusPages.textContent = `PDF: ${S.pages.length} page(s) loaded`;

  if (S.sigImg) {
    statusSig.className = 'ok';
    statusSig.textContent = 'Signature: loaded';
  } else {
    statusSig.className = 'warn';
    statusSig.textContent = 'Signature: none';
  }

  if (S.mode === 'signature') {
    if (S.sigImg) {
      statusHint.textContent = 'Click or drag on the PDF to place signature';
    } else {
      statusHint.className = 'warn';
      statusHint.textContent = '← Load a signature image first';
    }
  } else {
    const txt = textInput.value.trim();
    if (txt) {
      statusHint.className = 'ok';
      statusHint.textContent = 'Click on the PDF to place text';
    } else {
      statusHint.className = 'warn';
      statusHint.textContent = '← Type text in the sidebar first';
    }
  }
}

// requestAnimationFrame loop
let rafId = null;
function scheduleRender() {
  if (rafId) return;
  rafId = requestAnimationFrame(() => { rafId = null; drawFrame(); });
}

// ── Upload PDF ────────────────────────────────────────────────────────────────

async function loadPDF(file) {
  showLoading('Loading PDF…');
  try {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch('/api/upload-pdf', { method: 'POST', body: fd });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    S.sessionId  = data.session_id;
    S.pages      = data.pages.map(p => ({ ...p, img: null }));
    S.placements = [];
    computePageOffsets();

    topFilename.textContent = data.filename;
    saveBtn.disabled = false;
    dropHint.style.display = 'none';
    canvas.style.display = 'block';

    // Temporarily size canvas to prevent reflow jank
    canvas.width  = totalCanvasWidth();
    canvas.height = totalCanvasHeight();

    renderPlacementsList();
    updateStatusBar();

    // Load page images in parallel
    await Promise.all(S.pages.map((_, i) => loadPageImage(i)));

    scheduleRender();
    showToast(`Loaded ${S.pages.length} page(s)`, 'success');
  } catch (err) {
    showToast('Failed to load PDF: ' + err.message, 'error');
    console.error(err);
  } finally {
    hideLoading();
  }
}

async function loadPageImage(i) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload  = () => { S.pages[i].img = img; scheduleRender(); resolve(); };
    img.onerror = () => resolve();
    img.src     = `/api/page/${S.sessionId}/${i}`;
  });
}

// ── Upload Signature ──────────────────────────────────────────────────────────

async function loadSignature(file) {
  if (!S.sessionId) {
    showToast('Load a PDF first', 'error');
    return;
  }
  showLoading('Processing signature…');
  try {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('session_id', S.sessionId);
    const res = await fetch('/api/upload-signature', { method: 'POST', body: fd });
    if (!res.ok) throw new Error(await res.text());
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);

    const img = new Image();
    img.onload = () => {
      S.sigImg = img;
      // Keep the default width and derive the height from the image ratio
      S.sigH = Math.max(4, Math.round(S.sigW * img.naturalHeight / img.naturalWidth));
      sigH.value = S.sigH;
      // Show sidebar preview
      sigPreview.src    = url;
      sigPreview.style.display = 'block';
      sigFilename.textContent  = file.name;
      updateStatusBar();
      scheduleRender();
    };
    img.src = url;
    showToast('Signature loaded', 'success');
  } catch (err) {
    showToast('Failed to load signature: ' + err.message, 'error');
    console.error(err);
  } finally {
    hideLoading();
  }
}

// ── Sign & Save ───────────────────────────────────────────────────────────────

async function savePDF() {
  if (!S.sessionId) return;
  if (!S.placements.length) {
    showToast('Add at least one placement first', 'error');
    return;
  }
  showLoading('Generating signed PDF…');
  try {
    const body = {
      session_id: S.sessionId,
      placements: S.placements.map(p => ({
        type:  p.type,
        page:  p.page,
        cx:    p.cx,
        cy:    p.cy,
        w:     p.w    || 0,
        h:     p.h    || 0,
        text:  p.text || '',
        size:  p.size || 12,
        color: p.color || '#000000',
      })),
    };
    const res = await fetch('/api/sign', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'signed.pdf';
    a.click();
    URL.revokeObjectURL(url);
    showToast('Signed PDF downloaded!', 'success');
  } catch (err) {
    showToast('Error saving: ' + err.message, 'error');
    console.error(err);
  } finally {
    hideLoading();
  }
}

// ── Placements management ─────────────────────────────────────────────────────

function addPlacement(pl) {
  S.placements.push(pl);
  undoBtn.disabled = false;
  renderPlacementsList();
  scheduleRender();
}

function removePlacement(idx) {
  S.placements.splice(idx, 1);
  undoBtn.disabled = S.placements.length === 0;
  renderPlacementsList();
  scheduleRender();
}

function undoLast() {
  if (!S.placements.length) return;
  S.placements.pop();
  undoBtn.disabled = S.placements.length === 0;
  renderPlacementsList();
  scheduleRender();
}

function renderPlacementsList() {
  placList.innerHTML = '';
  S.placements.forEach((pl, i) => {
    const li = document.createElement('li');
    li.className = 'placement-item';

    const badge = document.createElement('span');
    badge.className = 'placement-badge ' + (pl.type === 'signature' ? 'badge-sig' : 'badge-txt');
    badge.textContent = pl.type === 'signature' ? 'SIG' : 'TXT';

    const label = document.createElement('span');
    label.className = 'placement-label';
    if (pl.type === 'signature') {
      label.textContent = `p${pl.page + 1} (${Math.round(pl.cx)},${Math.round(pl.cy)}) ${pl.w}×${pl.h}`;
    } else {
      label.textContent = `p${pl.page + 1} "${pl.text.slice(0, 14)}"`;
    }

    const del = document.createElement('button');
    del.className = 'del-btn';
    del.textContent = '×';
    del.title = 'Remove';
    del.addEventListener('click', (e) => {
      e.stopPropagation();
      removePlacement(i);
    });

    li.appendChild(badge);
    li.appendChild(label);
    li.appendChild(del);
    placList.appendChild(li);
  });
}

// ── Mouse / drag event handling ───────────────────────────────────────────────

canvas.addEventListener('mousedown', (e) => {
  if (!S.pages.length) return;
  if (e.button !== 0) return;
  e.preventDefault();
  const pos = eventToCanvas(e);
  S.dragStart  = pos;
  S.isDragging = false;
  S.mousePos   = pos;
  scheduleRender();
});

canvas.addEventListener('mousemove', (e) => {
  if (!S.pages.length) return;
  const pos = eventToCanvas(e);
  S.mousePos = pos;
  if (S.dragStart) S.isDragging = true;
  scheduleRender();
});

canvas.addEventListener('mouseleave', () => {
  S.mousePos   = { x: -9999, y: -9999 };
  S.isDragging = false;
  scheduleRender();
});

// mouseup on window so releasing outside the canvas still registers
window.addEventListener('mouseup', (e) => {
  if (!S.pages.length || !S.dragStart) return;
  if (e.button !== 0) return;

  // Compute release position relative to canvas
  const rect = canvas.getBoundingClientRect();
  const pos = {
    x: e.clientX - rect.left,
    y: e.clientY - rect.top,
  };

  const x0 = S.dragStart.x, y0 = S.dragStart.y;
  const x1 = pos.x,         y1 = pos.y;
  const dx = Math.abs(x1 - x0), dy = Math.abs(y1 - y0);
  const dragged = dx > DRAG_THRESHOLD || dy > DRAG_THRESHOLD;

  if (S.mode === 'signature') {
    if (!S.sigImg) {
      showToast('Load a signature image first', 'error');
    } else {
      if (dragged) {
        const rx0 = Math.min(x0, x1), ry0 = Math.min(y0, y1);
        const boxW = Math.abs(x1 - x0) / ZOOM;
        const boxH = Math.abs(y1 - y0) / ZOOM;
        const ratio = S.sigImg.naturalHeight / S.sigImg.naturalWidth;
        // Fit inside the drawn box while keeping the image proportions
        const w = Math.max(4, Math.round(Math.min(boxW, boxH / ratio)));
        const h = Math.max(4, Math.round(w * ratio));
        sigW.value = w;  sigH.value = h;
        S.sigW = w;      S.sigH = h;
        const pdf = canvasToPdf(rx0, ry0);
        addPlacement({ type: 'signature', page: pdf.page, cx: pdf.x, cy: pdf.y, w, h });
      } else {
        const pdf = canvasToPdf(x0, y0);
        addPlacement({ type: 'signature', page: pdf.page, cx: pdf.x, cy: pdf.y, w: S.sigW, h: S.sigH });
      }
    }
  } else if (S.mode === 'text') {
    const text = textInput.value.trim();
    if (!text) {
      showToast('Type text in the sidebar first', 'error');
    } else {
      const pdf   = canvasToPdf(x0, y0);
      const size  = Math.max(4, parseFloat(fontSizeEl.value) || 12);
      const color = fontColorEl.value || '#000000';
      addPlacement({ type: 'text', page: pdf.page, cx: pdf.x, cy: pdf.y, text, size, color });
    }
  }

  S.dragStart  = null;
  S.isDragging = false;
  scheduleRender();
});

// ── Drag-and-drop onto canvas area ────────────────────────────────────────────

canvasWrap.addEventListener('dragenter', (e) => {
  e.preventDefault();
  canvasWrap.classList.add('dragover');
});
canvasWrap.addEventListener('dragover', (e) => {
  e.preventDefault();
});
canvasWrap.addEventListener('dragleave', (e) => {
  if (!canvasWrap.contains(e.relatedTarget)) {
    canvasWrap.classList.remove('dragover');
  }
});
canvasWrap.addEventListener('drop', (e) => {
  e.preventDefault();
  canvasWrap.classList.remove('dragover');
  const files = e.dataTransfer.files;
  if (!files.length) return;
  const file = files[0];
  if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
    loadPDF(file);
  } else if (file.type.startsWith('image/')) {
    loadSignature(file);
  }
});

// ── File input buttons ────────────────────────────────────────────────────────

pdfInput.addEventListener('change', () => {
  if (pdfInput.files[0]) loadPDF(pdfInput.files[0]);
  pdfInput.value = '';
});

sigInput.addEventListener('change', () => {
  if (sigInput.files[0]) loadSignature(sigInput.files[0]);
  sigInput.value = '';
});

// ── Sidebar spinbox sync ──────────────────────────────────────────────────────

// W and H stay linked to the signature's aspect ratio so it never looks stretched
function sigRatio() {
  return S.sigImg ? S.sigImg.naturalHeight / S.sigImg.naturalWidth : null;
}

sigW.addEventListener('input', () => {
  S.sigW = Math.max(4, parseInt(sigW.value, 10) || 120);
  const ratio = sigRatio();
  if (ratio) { S.sigH = Math.max(4, Math.round(S.sigW * ratio)); sigH.value = S.sigH; }
  scheduleRender();
});
sigH.addEventListener('input', () => {
  S.sigH = Math.max(4, parseInt(sigH.value, 10) || 50);
  const ratio = sigRatio();
  if (ratio) { S.sigW = Math.max(4, Math.round(S.sigH / ratio)); sigW.value = S.sigW; }
  scheduleRender();
});

// ── Mode toggle ───────────────────────────────────────────────────────────────

modeInputs.forEach(input => {
  input.addEventListener('change', () => {
    S.mode = input.value;
    sigSection.style.display  = S.mode === 'signature' ? '' : 'none';
    textSection.style.display = S.mode === 'text'      ? '' : 'none';
    S.mousePos = { x: -9999, y: -9999 };
    updateStatusBar();
    scheduleRender();
  });
});

// ── Text input → re-render ghost ──────────────────────────────────────────────

textInput.addEventListener('input', () => { updateStatusBar(); scheduleRender(); });
fontSizeEl.addEventListener('input', scheduleRender);
fontColorEl.addEventListener('input', () => {
  fontColorHex.textContent = fontColorEl.value;
  scheduleRender();
});

// ── Toolbar buttons ───────────────────────────────────────────────────────────

saveBtn.addEventListener('click', savePDF);
undoBtn.addEventListener('click', undoLast);
