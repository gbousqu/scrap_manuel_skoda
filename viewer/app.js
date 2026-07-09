const manualSlug = new URLSearchParams(location.search).get("manual");
if (!manualSlug) {
  location.replace("index.html");
  throw new Error("redirect");
}

const manualBase = new URL(`../manuals/${manualSlug}/`, import.meta.url);
const manifestUrl = new URL("manifest.json", manualBase);
const searchIndexUrl = new URL("search_index.json", manualBase);
const chaptersBase = new URL("chapters/", manualBase);
const mediaBase = new URL("media/", manualBase);

let manifest = null;
let flatTopics = [];
let topicById = {};
let currentTopicId = null;
let searchIndex = null;
let activeSearchQuery = "";
let searchActiveIndex = -1;
let searchResultItems = [];
let pathToTopicId = new Map();

const BREADCRUMB_SEP = " › ";

const searchInput = () => document.getElementById("search");
const searchDropdown = () => document.getElementById("search-dropdown");

async function init() {
  const [manifestRes, indexRes] = await Promise.all([
    fetch(manifestUrl),
    fetch(searchIndexUrl),
  ]);
  manifest = await manifestRes.json();
  document.getElementById("manual-title").textContent = manifest.title || `Manuel ${manualSlug}`;
  document.title = manifest.title || `Manuel Škoda — ${manualSlug}`;
  if (!indexRes.ok) {
    throw new Error("search_index.json introuvable — lancez python build_search_index.py");
  }
  searchIndex = await indexRes.json();

  flatTopics = manifest.flatTopics || [];
  topicById = Object.fromEntries(flatTopics.map((t) => [t.topicId, t]));
  pathToTopicId = buildPathIndex(manifest.tree || []);
  renderTree(manifest.tree || [], document.getElementById("tree"));

  const input = searchInput();
  input.addEventListener("input", onSearchInput);
  input.addEventListener("search", onSearchInput);
  input.addEventListener("keydown", onSearchKeydown);
  input.addEventListener("focus", () => {
    if (input.value.trim()) onSearchInput({ target: input });
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".search-wrap")) hideSearchDropdown();
  });

  document.getElementById("btn-prev").addEventListener("click", () => navigateRelative(-1));
  document.getElementById("btn-next").addEventListener("click", () => navigateRelative(1));
  document.getElementById("btn-export-pdf").addEventListener("click", startPdfExport);
  document.getElementById("pdf-modal-cancel").addEventListener("click", cancelPdfExport);
  document.getElementById("content").addEventListener("click", (e) => {
    const link = e.target.closest("a[data-topic-id], a[href^='#topic/']");
    if (!link) return;
    e.preventDefault();
    const topicId =
      link.dataset.topicId || link.getAttribute("href")?.replace(/^#topic\//, "");
    if (topicId) location.hash = `#topic/${topicId}`;
  });
  window.addEventListener("hashchange", onHashChange);
  onHashChange();
}

function normalizeQuery(q) {
  return q.trim().toLowerCase().replace(/\s+/g, " ");
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function rankTerm(term, q) {
  if (term === q) return 0;
  if (term.startsWith(q)) return 1;
  return 2;
}

function findTerms(q, limit = 10) {
  if (!searchIndex || q.length < 2) return [];
  const hits = [];
  for (const term of searchIndex.terms) {
    if (!term.includes(q)) continue;
    hits.push(term);
    if (hits.length >= 200) break;
  }
  hits.sort((a, b) => {
    const ra = rankTerm(a, q);
    const rb = rankTerm(b, q);
    if (ra !== rb) return ra - rb;
    return a.length - b.length || a.localeCompare(b, "fr");
  });
  return hits.slice(0, limit);
}

function scoreTopic(topic, q) {
  let score = 0;
  const title = topic.title.toLowerCase();
  const path = (topic.path || []).join(" ").toLowerCase();
  if (title.includes(q)) score += 120;
  if (path.includes(q)) score += 40;
  const matches = topic.text.match(new RegExp(escapeRegex(q), "g"));
  score += (matches ? matches.length : 0) * 8;
  return score;
}

function makeSnippet(text, q, radius = 55) {
  const i = text.indexOf(q);
  if (i < 0) return "";
  const start = Math.max(0, i - radius);
  const end = Math.min(text.length, i + q.length + radius);
  let snippet = text.slice(start, end).trim();
  if (start > 0) snippet = "…" + snippet;
  if (end < text.length) snippet = snippet + "…";
  return snippet;
}

function findPages(q, limit = 20) {
  if (!searchIndex || q.length < 2) return [];
  const hits = [];
  for (const topic of searchIndex.topics) {
    if (!topic.text.includes(q) && !topic.title.toLowerCase().includes(q)) continue;
    const score = scoreTopic(topic, q);
    if (score <= 0) continue;
    hits.push({
      type: "page",
      topicId: topic.topicId,
      title: topic.title,
      path: topic.path,
      snippet: makeSnippet(topic.text, q),
      score,
    });
  }
  hits.sort((a, b) => b.score - a.score || a.title.localeCompare(b.title, "fr"));
  return hits.slice(0, limit);
}

function buildSearchResults(q) {
  const terms = findTerms(q, 8);
  const pages = findPages(q, 15);
  const results = [];

  for (const term of terms) {
    results.push({ type: "term", term, label: term });
  }
  for (const page of pages) {
    results.push(page);
  }
  return results;
}

function hideSearchDropdown() {
  const dd = searchDropdown();
  dd.classList.add("hidden");
  dd.innerHTML = "";
  searchActiveIndex = -1;
  searchResultItems = [];
}

function highlightSnippet(snippet, q) {
  if (!snippet || !q) return "";
  const re = new RegExp(`(${escapeRegex(q)})`, "gi");
  return snippet.replace(re, "<mark>$1</mark>");
}

function renderSearchDropdown(results, q) {
  const dd = searchDropdown();
  searchResultItems = results;
  searchActiveIndex = results.length ? 0 : -1;

  if (!results.length) {
    dd.innerHTML = `<div class="search-empty">Aucun résultat pour « ${escapeHtml(q)} »</div>`;
    dd.classList.remove("hidden");
    return;
  }

  dd.innerHTML = results
    .map((item, i) => {
      if (item.type === "term") {
        return `<button type="button" class="search-item search-term${i === 0 ? " active" : ""}" data-index="${i}" role="option">
          <span class="search-item-label">${escapeHtml(item.label)}</span>
          <span class="search-item-arrow" aria-hidden="true">↗</span>
        </button>`;
      }
      const path = (item.path || []).slice(0, -1).join(" › ");
      const snippet = highlightSnippet(item.snippet, q);
      return `<button type="button" class="search-item search-page${i === 0 ? " active" : ""}" data-index="${i}" role="option">
        <span class="search-item-title">${escapeHtml(item.title)}</span>
        ${path ? `<span class="search-item-path">${escapeHtml(path)}</span>` : ""}
        ${snippet ? `<span class="search-item-snippet">${snippet}</span>` : ""}
        <span class="search-item-arrow" aria-hidden="true">↗</span>
      </button>`;
    })
    .join("");

  dd.querySelectorAll(".search-item").forEach((btn) => {
    btn.addEventListener("mousedown", (e) => {
      e.preventDefault();
      selectSearchResult(Number(btn.dataset.index));
    });
  });

  dd.classList.remove("hidden");
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function updateSearchActiveItem() {
  searchDropdown().querySelectorAll(".search-item").forEach((el, i) => {
    el.classList.toggle("active", i === searchActiveIndex);
    if (i === searchActiveIndex) el.scrollIntoView({ block: "nearest" });
  });
}

function selectSearchResult(index) {
  const item = searchResultItems[index];
  if (!item) return;

  if (item.type === "term") {
    const input = searchInput();
    input.value = item.term;
    activeSearchQuery = normalizeQuery(item.term);
    onSearchInput({ target: input });
    input.focus();
    return;
  }

  activeSearchQuery = normalizeQuery(searchInput().value);
  hideSearchDropdown();
  openTopic(item.topicId, activeSearchQuery);
  location.hash = `#topic/${item.topicId}`;
}

function onSearchInput(e) {
  const q = normalizeQuery(e.target.value);

  if (!e.target.value.trim()) {
    hideSearchDropdown();
    if (activeSearchQuery) {
      activeSearchQuery = "";
      clearSearchHighlights();
    }
    return;
  }

  activeSearchQuery = q;
  if (q.length < 2) {
    hideSearchDropdown();
    return;
  }
  renderSearchDropdown(buildSearchResults(q), q);
}

function onSearchKeydown(e) {
  const dd = searchDropdown();
  if (dd.classList.contains("hidden") || !searchResultItems.length) {
    if (e.key === "Enter" && activeSearchQuery.length >= 2) {
      const pages = findPages(activeSearchQuery, 1);
      if (pages[0]) {
        e.preventDefault();
        hideSearchDropdown();
        openTopic(pages[0].topicId, activeSearchQuery);
        location.hash = `#topic/${pages[0].topicId}`;
      }
    }
    return;
  }

  if (e.key === "ArrowDown") {
    e.preventDefault();
    searchActiveIndex = Math.min(searchActiveIndex + 1, searchResultItems.length - 1);
    updateSearchActiveItem();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    searchActiveIndex = Math.max(searchActiveIndex - 1, 0);
    updateSearchActiveItem();
  } else if (e.key === "Enter") {
    e.preventDefault();
    if (searchActiveIndex >= 0) selectSearchResult(searchActiveIndex);
  } else if (e.key === "Escape") {
    hideSearchDropdown();
  }
}

function getDensityFactor(src) {
  const match = (src || "").match(/_(1x|2x|3x)\.(png|svg|jpe?g|webp)/i);
  return match ? parseInt(match[1], 10) : 1;
}

function isFixedIcon(img) {
  const role = img.getAttribute("data-role");
  return img.classList.contains("icon") || role === "icon" || role === "safety-alert-symbol";
}

function isSymbolImage(img) {
  return img.classList.contains("symbol") || img.getAttribute("data-role") === "symbol";
}

function isBlockImage(img) {
  return img.classList.contains("blockimage");
}

function scaleManualImages(root) {
  root.querySelectorAll("img").forEach((img) => {
    if (img.dataset.manualScaled) return;
    img.dataset.manualScaled = "1";

    const applyScale = () => {
      if (isFixedIcon(img) || isBlockImage(img) || isSymbolImage(img)) return;
      if (!img.naturalWidth) return;

      const src = img.currentSrc || img.src || img.dataset.src || "";
      const density = getDensityFactor(src);
      const inFigure = !!img.closest("figure, [data-type='illu']");

      if (img.naturalWidth >= 600) return;

      if (inFigure && density > 1 && img.naturalWidth < 600) {
        const displayW = Math.round(img.naturalWidth / density);
        img.style.width = `${displayW}px`;
        img.style.height = "auto";
        img.style.maxWidth = "100%";
      }
    };

    if (img.complete && img.naturalWidth) applyScale();
    else img.addEventListener("load", applyScale, { once: true });
  });
}

function resolveMediaUrl(url) {
  if (!url) return url;
  if (url.startsWith("../media/")) {
    return new URL(url.slice("../media/".length), mediaBase).href;
  }
  if (url.startsWith("media/")) {
    return new URL(url.slice("media/".length), mediaBase).href;
  }
  return url;
}

/** Les chapitres HTML utilisent ../media/ (relatif au dossier manuel) ; le viewer est ailleurs. */
function fixMediaPaths(root) {
  for (const el of root.querySelectorAll("img, a, source")) {
    for (const attr of ["src", "data-src", "data-href", "href"]) {
      const val = el.getAttribute(attr);
      if (!val || (!val.includes("../media/") && !val.startsWith("media/"))) continue;
      el.setAttribute(attr, resolveMediaUrl(val));
    }
  }
}

function prepareChapterImages(root) {
  root.querySelectorAll("img[data-src]").forEach((img) => {
    if (!img.src && img.dataset.src) img.src = resolveMediaUrl(img.dataset.src);
  });
  scaleManualImages(root);
}

function highlightTextInContent(root, query) {
  if (!query || query.length < 2) return;
  const re = new RegExp(escapeRegex(query), "gi");
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
      if (node.parentElement?.closest("script, style")) return NodeFilter.FILTER_REJECT;
      return re.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    },
  });

  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);

  for (const node of nodes) {
    const text = node.nodeValue;
    re.lastIndex = 0;
    if (!re.test(text)) continue;
    re.lastIndex = 0;
    const span = document.createElement("span");
    span.className = "search-highlight-wrap";
    span.innerHTML = text.replace(re, '<mark class="search-hit">$&</mark>');
    node.parentNode.replaceChild(span, node);
  }

  const first = root.querySelector("mark.search-hit");
  if (first) first.scrollIntoView({ block: "center", behavior: "smooth" });
}

function clearSearchHighlights(root = document.getElementById("content")) {
  root.querySelectorAll("mark.search-hit").forEach((mark) => {
    mark.replaceWith(document.createTextNode(mark.textContent));
  });
  root.querySelectorAll("span.search-highlight-wrap").forEach((span) => {
    span.replaceWith(...span.childNodes);
  });
  root.normalize();
}

function pathKey(path) {
  return path.join(BREADCRUMB_SEP);
}

function firstTopicIdInNode(node) {
  if (node.topicId) return node.topicId;
  for (const child of node.children || []) {
    const id = firstTopicIdInNode(child);
    if (id) return id;
  }
  return null;
}

function buildPathIndex(nodes) {
  const index = new Map();

  function walk(nodeList, trail) {
    for (const node of nodeList) {
      const path = [...trail, node.title];
      const key = pathKey(path);
      const target = node.topicId || firstTopicIdInNode(node);
      if (target) index.set(key, target);
      if (node.children?.length) walk(node.children, path);
    }
  }

  walk(nodes, []);
  return index;
}

function navigateToTopic(topicId) {
  activeSearchQuery = "";
  hideSearchDropdown();
  location.hash = `#topic/${topicId}`;
}

function renderBreadcrumb(path) {
  const el = document.getElementById("breadcrumb");
  el.innerHTML = "";

  if (!path?.length) return;

  path.forEach((segment, i) => {
    if (i > 0) {
      const sep = document.createElement("span");
      sep.className = "breadcrumb-sep";
      sep.textContent = BREADCRUMB_SEP;
      el.appendChild(sep);
    }

    const isLast = i === path.length - 1;
    const topicId = pathToTopicId.get(pathKey(path.slice(0, i + 1)));

    if (!isLast && topicId) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "breadcrumb-link";
      btn.textContent = segment;
      btn.addEventListener("click", () => navigateToTopic(topicId));
      el.appendChild(btn);
    } else {
      const span = document.createElement("span");
      span.className = isLast ? "breadcrumb-current" : "breadcrumb-text";
      span.textContent = segment;
      el.appendChild(span);
    }
  });
}

function onHashChange() {
  const m = location.hash.match(/^#topic\/(.+)$/);
  if (m) openTopic(m[1], activeSearchQuery);
}

function renderTree(nodes, container) {
  container.innerHTML = "";
  for (const node of nodes) {
    container.appendChild(renderNode(node));
  }
}

function renderNode(node) {
  const wrap = document.createElement("div");
  wrap.className = "node";

  const hasChildren = node.children && node.children.length > 0;
  const isLeaf = !!node.topicId;

  if (isLeaf || hasChildren) {
    const row = document.createElement("div");
    row.className = "row" + (isLeaf ? " leaf" : " folder");
    row.style.setProperty("--depth", node.depth || 0);
    if (isLeaf) {
      row.dataset.topicId = node.topicId;
      row.dataset.title = node.title;
      row.addEventListener("click", () => {
        activeSearchQuery = "";
        location.hash = `#topic/${node.topicId}`;
      });
    }

    const toggle = document.createElement("span");
    toggle.className = "toggle";
    toggle.textContent = hasChildren ? "▸" : "";
    if (hasChildren) {
      toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        const ch = wrap.querySelector(".children");
        const open = ch.classList.toggle("open");
        toggle.textContent = open ? "▾" : "▸";
      });
    }
    row.appendChild(toggle);

    const label = document.createElement("span");
    label.textContent = node.title;
    row.appendChild(label);
    wrap.appendChild(row);
  }

  if (hasChildren) {
    const children = document.createElement("div");
    children.className = "children open";
    for (const child of node.children) {
      children.appendChild(renderNode(child));
    }
    wrap.appendChild(children);
  }

  return wrap;
}

async function openTopic(topicId, highlightQuery = "") {
  const meta = topicById[topicId];
  if (!meta || !meta.file) {
    document.getElementById("content").innerHTML =
      "<p>Ce chapitre n'a pas de contenu téléchargé.</p>";
    return;
  }

  currentTopicId = topicId;
  document.querySelectorAll("#tree .row.active").forEach((r) => r.classList.remove("active"));
  const active = document.querySelector(`#tree .row[data-topic-id="${topicId}"]`);
  if (active) {
    active.classList.add("active");
    let parent = active.closest(".children");
    while (parent) {
      parent.classList.add("open");
      const toggle = parent.previousElementSibling?.querySelector(".toggle");
      if (toggle) toggle.textContent = "▾";
      parent = parent.parentElement?.closest(".children");
    }
    active.scrollIntoView({ block: "nearest" });
  }

  renderBreadcrumb(meta.path || [meta.title]);
  document.getElementById("placeholder")?.remove();

  const chapterFile = meta.file.replace(/^chapters[/\\]/, "");
  const res = await fetch(new URL(chapterFile, chaptersBase), { cache: "no-store" });
  if (!res.ok) {
    document.getElementById("content").innerHTML =
      `<p>Chapitre introuvable (${res.status}) : ${chapterFile}</p>`;
    return;
  }
  const html = await res.text();
  const doc = new DOMParser().parseFromString(html, "text/html");
  const body = doc.body.innerHTML;
  const content = document.getElementById("content");
  content.innerHTML = body;
  fixMediaPaths(content);
  prepareChapterImages(content);
  if (highlightQuery) highlightTextInContent(content, highlightQuery);

  updateNavButtons();
}

function navigateRelative(delta) {
  const idx = flatTopics.findIndex((t) => t.topicId === currentTopicId);
  if (idx < 0) return;
  const next = flatTopics[idx + delta];
  if (next) location.hash = `#topic/${next.topicId}`;
}

function updateNavButtons() {
  const idx = flatTopics.findIndex((t) => t.topicId === currentTopicId);
  document.getElementById("btn-prev").disabled = idx <= 0;
  document.getElementById("btn-next").disabled = idx < 0 || idx >= flatTopics.length - 1;
}

const pdfApiUrl = new URL("generate_pdf.php", import.meta.url);
let pdfPollTimer = null;
let pdfExportActive = false;

function pdfModalEl() {
  return document.getElementById("pdf-modal");
}

function showPdfModal(message, { progress = null, phase = "" } = {}) {
  const modal = pdfModalEl();
  modal.classList.remove("hidden");
  document.getElementById("pdf-modal-message").textContent = message;

  const wrap = document.getElementById("pdf-progress-wrap");
  const fill = document.getElementById("pdf-progress-fill");
  const label = document.getElementById("pdf-progress-label");

  if (progress && progress.total > 0) {
    wrap.classList.remove("hidden");
    const pct = Math.min(100, Math.round((progress.current / progress.total) * 100));
    fill.style.width = `${pct}%`;
    const phaseLabels = {
      pdf: "Rendu PDF",
      merge: "Fusion",
      html: "Préparation",
      start: "Démarrage",
    };
    const phaseLabel = phaseLabels[phase] || "Génération";
    label.textContent = `${phaseLabel} : ${progress.current} / ${progress.total} (${pct} %)`;
  } else if (phase === "pdf" || phase === "merge" || phase === "start") {
    wrap.classList.remove("hidden");
    fill.style.width = phase === "start" ? "12%" : "100%";
    const waitMsg = {
      start: "Lancement de Python et Playwright…",
      pdf: "Rendu PDF en cours (plusieurs minutes)…",
      merge: "Fusion des lots PDF…",
    };
    label.textContent = waitMsg[phase] || "Génération en cours…";
  } else {
    wrap.classList.add("hidden");
    fill.style.width = "0%";
    label.textContent = "";
  }
}

function hidePdfModal() {
  pdfModalEl().classList.add("hidden");
}

function clearPdfPollTimer() {
  if (pdfPollTimer) {
    clearTimeout(pdfPollTimer);
    pdfPollTimer = null;
  }
}

function stopPdfPolling() {
  clearPdfPollTimer();
  pdfExportActive = false;
  document.getElementById("btn-export-pdf").disabled = false;
}

function cancelPdfExport() {
  stopPdfPolling();
  hidePdfModal();
}

function triggerPdfDownload() {
  const url = new URL(pdfApiUrl);
  url.searchParams.set("action", "download");
  url.searchParams.set("manual", manualSlug);
  const a = document.createElement("a");
  a.href = url.toString();
  a.download = `manuel_skoda_${manualSlug}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function fetchPdfStatus() {
  const url = new URL(pdfApiUrl);
  url.searchParams.set("action", "status");
  url.searchParams.set("manual", manualSlug);
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "Statut PDF indisponible");
  return data.status || { state: "idle" };
}

function schedulePdfPoll(delayMs = 1500) {
  clearPdfPollTimer();
  pdfExportActive = true;
  pdfPollTimer = setTimeout(pollPdfStatus, delayMs);
}

async function pollPdfStatus() {
  if (!pdfExportActive) return;

  try {
    const status = await fetchPdfStatus();
    const state = status.state || "idle";

    if (state === "building") {
      const phase = status.phase || "html";
      const progress =
        status.total > 0
          ? { current: status.progress || 0, total: status.total }
          : null;
      showPdfModal(status.message || "Génération du PDF en cours…", { progress, phase });
      pdfPollTimer = setTimeout(pollPdfStatus, 1200);
      return;
    }

    if (state === "done") {
      showPdfModal("PDF prêt — téléchargement en cours…");
      triggerPdfDownload();
      setTimeout(() => {
        hidePdfModal();
        stopPdfPolling();
      }, 1200);
      return;
    }

    if (state === "error") {
      hidePdfModal();
      stopPdfPolling();
      alert(`Erreur PDF : ${status.message || "échec inconnu"}`);
      return;
    }

    pdfPollTimer = setTimeout(pollPdfStatus, 1500);
  } catch (err) {
    hidePdfModal();
    stopPdfPolling();
    alert(
      `Impossible de suivre la génération PDF.\n${err.message}\n\n` +
        "Vérifiez que le viewer est servi via WAMP (http://localhost/...) " +
        "et que PHP peut exécuter Python.\n" +
        "Alternative : python build_manual_pdf.py"
    );
  }
}

async function startPdfExport() {
  if (pdfExportActive) return;

  const btn = document.getElementById("btn-export-pdf");
  btn.disabled = true;
  pdfExportActive = true;
  showPdfModal("Démarrage de la génération PDF…");

  try {
    const url = new URL(pdfApiUrl);
    url.searchParams.set("action", "start");
    url.searchParams.set("manual", manualSlug);
    const res = await fetch(url, { cache: "no-store" });
    const data = await res.json();

    if (!res.ok || !data.ok) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }

    schedulePdfPoll(800);
  } catch (err) {
    hidePdfModal();
    stopPdfPolling();
    alert(
      `Impossible de lancer l'export PDF.\n${err.message}\n\n` +
        "Le viewer doit être ouvert via WAMP avec PHP activé.\n" +
        "Vous pouvez aussi lancer : python build_manual_pdf.py"
    );
  }
}

init().catch((err) => {
  document.body.innerHTML = `<pre style="padding:2rem;color:red">Erreur: ${err.message}</pre>`;
});
