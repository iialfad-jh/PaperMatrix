import * as pdfjsLib from "/assets/pdfjs/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = "/assets/pdfjs/pdf.worker.min.mjs";

let activeDocument = null;
let activeUrl = null;
let renderVersion = 0;

function normalizedText(value) {
  return String(value || "")
    .normalize("NFKC")
    .toLocaleLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function evidenceTerms(value) {
  const normalized = normalizedText(value);
  const terms = new Set(normalized.match(/[\p{L}\p{N}][\p{L}\p{N}_-]{3,}/gu) || []);
  return [...terms].slice(0, 80);
}

function matchingItems(items, evidenceText) {
  const normalizedEvidence = normalizedText(evidenceText);
  const terms = evidenceTerms(evidenceText);
  if (!normalizedEvidence || !terms.length) return [];

  return items.filter((item) => {
    const text = normalizedText(item.str);
    if (text.length < 3) return false;
    if (text.length >= 4 && normalizedEvidence.includes(text)) return true;
    return terms.some((term) => text.includes(term) || term.includes(text));
  }).slice(0, 80);
}

function highlightElement(item, viewport) {
  const transform = pdfjsLib.Util.transform(viewport.transform, item.transform);
  const fontHeight = Math.max(8, Math.hypot(transform[2], transform[3]));
  const highlight = document.createElement("span");
  highlight.className = "pdf-highlight";
  highlight.style.left = `${transform[4]}px`;
  highlight.style.top = `${transform[5] - fontHeight}px`;
  highlight.style.width = `${Math.max(8, item.width * viewport.scale)}px`;
  highlight.style.height = `${fontHeight}px`;
  return highlight;
}

async function loadDocument(url) {
  if (activeDocument && activeUrl === url) return activeDocument;
  if (activeDocument) await activeDocument.destroy();
  activeDocument = await pdfjsLib.getDocument({ url }).promise;
  activeUrl = url;
  return activeDocument;
}

async function renderEvidencePage({ container, url, pageNumber, evidenceText }) {
  const version = ++renderVersion;
  container.replaceChildren();
  const loading = document.createElement("p");
  loading.className = "pdf-loading";
  loading.textContent = "正在加载证据页…";
  container.append(loading);

  const pdf = await loadDocument(url);
  const selectedPage = Math.min(Math.max(1, Number(pageNumber) || 1), pdf.numPages);
  const page = await pdf.getPage(selectedPage);
  const baseViewport = page.getViewport({ scale: 1 });
  const availableWidth = Math.max(320, container.clientWidth - 28);
  const scale = Math.min(1.5, Math.max(0.7, availableWidth / baseViewport.width));
  const viewport = page.getViewport({ scale });
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d", { alpha: false });
  const outputScale = window.devicePixelRatio || 1;
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;

  const pageSurface = document.createElement("div");
  pageSurface.className = "pdf-page-surface";
  pageSurface.style.width = `${viewport.width}px`;
  pageSurface.style.height = `${viewport.height}px`;
  pageSurface.append(canvas);

  await page.render({
    canvasContext: context,
    viewport,
    transform: outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0],
  }).promise;
  const textContent = await page.getTextContent();
  const matches = matchingItems(textContent.items, evidenceText);
  matches.forEach((item) => pageSurface.append(highlightElement(item, viewport)));

  if (version !== renderVersion) return null;
  container.replaceChildren(pageSurface);
  return { pageNumber: selectedPage, pageCount: pdf.numPages, matchCount: matches.length };
}

function clearPdfViewer() {
  renderVersion += 1;
  activeDocument?.destroy();
  activeDocument = null;
  activeUrl = null;
}

window.PaperMatrixPdfViewer = { renderEvidencePage, clearPdfViewer };
