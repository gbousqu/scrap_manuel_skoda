const indexUrl = new URL("../manuals/index.json", import.meta.url);
const scrapeApiUrl = new URL("scrape_control.php", import.meta.url);

let scrapePollTimer = null;

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("fr-FR", {
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  } catch {
    return "";
  }
}

function initTabs() {
  const tabs = document.querySelectorAll(".nav-tab");
  const panels = {
    scrape: document.getElementById("panel-scrape"),
    browse: document.getElementById("panel-browse"),
  };

  const activate = (name) => {
    tabs.forEach((tab) => {
      const on = tab.dataset.tab === name;
      tab.classList.toggle("active", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
    Object.entries(panels).forEach(([key, panel]) => {
      const on = key === name;
      panel.classList.toggle("hidden", !on);
      panel.classList.toggle("active", on);
      panel.hidden = !on;
    });
    if (name === "browse") loadManualList();
    location.hash = name === "browse" ? "#consulter" : "#scraper";
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => activate(tab.dataset.tab));
  });

  if (location.hash === "#consulter") activate("browse");
  else activate("scrape");
}

async function loadManualList() {
  const list = document.getElementById("manual-list");
  const empty = document.getElementById("home-empty");
  if (!list) return;

  let index;
  try {
    const res = await fetch(indexUrl);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    index = await res.json();
  } catch (err) {
    list.innerHTML = `<li class="home-error">Impossible de charger manuals/index.json : ${escapeHtml(err.message)}</li>`;
    return;
  }

  const saves = Object.entries(index.saves || {});
  if (!saves.length) {
    list.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");

  saves.sort((a, b) => (a[1].title || a[0]).localeCompare(b[1].title || b[0], "fr"));

  list.innerHTML = saves
    .map(([slug, meta]) => {
      const title = meta.title || slug;
      const chapters = meta.topicCount ? `${meta.topicCount} chapitres` : "";
      const edition = meta.releaseDateLabel ? `Édition ${meta.releaseDateLabel}` : "";
      const updated = formatDate(meta.updatedAt);
      const vin = meta.vin ? `VIN …${meta.vin.slice(-4)}` : "";
      const metaLine = [chapters, edition, updated, vin].filter(Boolean).join(" · ");
      return `<li class="manual-card">
        <a href="read.html?manual=${encodeURIComponent(slug)}" class="manual-card-link">
          <span class="manual-card-title">${escapeHtml(title)}</span>
          <span class="manual-card-meta">${escapeHtml(metaLine)}</span>
        </a>
      </li>`;
    })
    .join("");
}

const STATE_LABELS = {
  idle: "Inactif",
  starting: "Démarrage",
  waiting_manual: "En attente",
  manual_ready: "Manuel détecté",
  scraping: "Téléchargement",
  done: "Terminé",
  error: "Erreur",
};

function showScrapeStatus(status) {
  const box = document.getElementById("scrape-status");
  const label = document.getElementById("scrape-status-label");
  const badge = document.getElementById("scrape-status-badge");
  const message = document.getElementById("scrape-status-message");
  const progressWrap = document.getElementById("scrape-progress-wrap");
  const progressFill = document.getElementById("scrape-progress-fill");
  const progressText = document.getElementById("scrape-progress-text");
  const doneLink = document.getElementById("scrape-done-link");
  const btn = document.getElementById("btn-start-scrape");

  const state = status?.state || "idle";
  if (state === "idle") {
    box.classList.add("hidden");
    btn.disabled = false;
    return;
  }

  box.classList.remove("hidden");
  label.textContent = "État du scraping";
  badge.textContent = STATE_LABELS[state] || state;
  badge.dataset.state = state;
  message.textContent = status.message || "";

  const running = ["starting", "waiting_manual", "manual_ready", "scraping"].includes(state);
  btn.disabled = running;

  const resetBtn = document.getElementById("btn-reset-scrape");
  if (resetBtn) {
    resetBtn.classList.remove("hidden");
  }

  if (state === "scraping" && status.total > 0) {
    progressWrap.classList.remove("hidden");
    const pct = Math.min(100, Math.round((status.progress / status.total) * 100));
    progressFill.style.width = `${pct}%`;
    progressText.textContent = `${status.progress} / ${status.total} chapitres (${pct} %)`;
  } else {
    progressWrap.classList.add("hidden");
  }

  if (state === "done" && status.slug) {
    doneLink.href = `read.html?manual=${encodeURIComponent(status.slug)}`;
    doneLink.textContent = `Ouvrir ${status.title || status.slug}`;
    doneLink.classList.remove("hidden");
    loadManualList();
  } else {
    doneLink.classList.add("hidden");
  }
}

async function fetchScrapeStatus() {
  const url = new URL(scrapeApiUrl);
  url.searchParams.set("action", "status");
  const res = await fetch(url, { cache: "no-store" });
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "Statut indisponible");
  return data.status || { state: "idle" };
}

function scheduleScrapePoll(delay = 1500) {
  clearTimeout(scrapePollTimer);
  scrapePollTimer = setTimeout(pollScrapeStatus, delay);
}

async function pollScrapeStatus() {
  try {
    const status = await fetchScrapeStatus();
    showScrapeStatus(status);
    const state = status.state || "idle";
    if (["starting", "waiting_manual", "manual_ready", "scraping"].includes(state)) {
      scheduleScrapePoll(state === "scraping" ? 1200 : 1800);
    }
  } catch {
    scheduleScrapePoll(3000);
  }
}

async function resetScrape() {
  const url = new URL(scrapeApiUrl);
  url.searchParams.set("action", "reset");
  const res = await fetch(url, { cache: "no-store" });
  const data = await res.json();
  if (data.ok) showScrapeStatus(data.status || { state: "idle" });
}

async function startScrape() {
  const btn = document.getElementById("btn-start-scrape");
  btn.disabled = true;
  showScrapeStatus({ state: "starting", message: "Lancement du navigateur…" });

  try {
    const url = new URL(scrapeApiUrl);
    url.searchParams.set("action", "start");
    const res = await fetch(url, { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    if (data.alreadyRunning) {
      showScrapeStatus(data.status || { state: "waiting_manual", message: "Scraping déjà en cours — cherchez la fenêtre Chromium." });
      scheduleScrapePoll(800);
      return;
    }
    scheduleScrapePoll(800);
  } catch (err) {
    showScrapeStatus({ state: "error", message: err.message });
    btn.disabled = false;
    alert(`Impossible de lancer le scraping.\n${err.message}`);
  }
}

function initScrape() {
  document.getElementById("btn-start-scrape")?.addEventListener("click", startScrape);
  document.getElementById("btn-reset-scrape")?.addEventListener("click", resetScrape);
  pollScrapeStatus();
}

initTabs();
initScrape();
