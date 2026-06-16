// BCR Agent — Nostr client for GitHub Pages
// Fetches kind 1 + kind 6500 (NIP-90 DVM) events from the bot npub,
// parses Blossom URLs and DVM metadata, renders workshop reports.
// Pure vanilla JS, no dependencies, no build step.

const BOT_NPUB_HEX = "9a515b0f08d554b582e54202c7ca0e6ee56d81559957cbf9b40047d391b95fd5";
const RELAYS = [
  "wss://nos.lol",
  "wss://relay.damus.io",
];
const BLOSSOM_SERVER = "https://blossom.psbt.me";
const FETCH_TIMEOUT_MS = 10000;

// --- State ---
let allRuns = [];
let selectedWorkshopId = null;

// =========================================================================
// WebSocket: Fetch Nostr events (kind 1 + kind 6500) from multiple relays
// =========================================================================

function fetchNostrEvents(pubkeyHex, kinds = [1, 6500], limit = 50) {
  return new Promise((resolve) => {
    const events = new Map(); // dedup by event id
    let resolved = false;
    let closedRelays = 0;
    let connectedCount = 0;

    const timeout = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        resolve({ events: [...events.values()], connected: connectedCount });
      }
    }, FETCH_TIMEOUT_MS);

    RELAYS.forEach((relayUrl) => {
      let ws;
      try {
        ws = new WebSocket(relayUrl);
      } catch (e) {
        closedRelays++;
        checkDone();
        return;
      }

      const subId = "bcr-" + Math.random().toString(36).slice(2, 8);

      ws.onopen = () => {
        connectedCount++;
        ws.send(JSON.stringify([
          "REQ", subId,
          {
            authors: [pubkeyHex],
            kinds,
            limit,
            since: Math.floor(Date.now() / 1000) - 86400 * 180, // last 180 days
          },
        ]));
        updateConnectionStatus(connectedCount, RELAYS.length);
      };

      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data);
          if (data[0] === "EVENT" && data[1] === subId && data[2]) {
            const evt = data[2];
            events.set(evt.id, evt);
          } else if (data[0] === "EOSE" && data[1] === subId) {
            ws.send(JSON.stringify(["CLOSE", subId]));
            ws.close();
          }
        } catch (e) { /* ignore parse errors */ }
      };

      ws.onerror = () => {
        closedRelays++;
        checkDone();
      };

      ws.onclose = () => {
        closedRelays++;
        checkDone();
      };
    });

    function checkDone() {
      if (closedRelays >= RELAYS.length && !resolved) {
        clearTimeout(timeout);
        resolved = true;
        resolve({ events: [...events.values()], connected: connectedCount });
      }
    }
  });
}

// =========================================================================
// Parsing: Extract workshop run data from Nostr events
// =========================================================================

function getTag(tags, name) {
  const t = (tags || []).find((tg) => tg[0] === name);
  return t ? t[1] : null;
}

function getParam(tags, name) {
  const t = (tags || []).find((tg) => tg[0] === "param" && tg[1] === name);
  return t ? t[2] : null;
}

function extractBlossomUrl(text) {
  if (!text) return null;
  const m = text.match(/(https:\/\/blossom\.psbt\.me\/[a-f0-9]+)/i);
  return m ? m[1] : null;
}

function extractPRInfo(text) {
  if (!text) return { prRef: null, prUrl: null, prTitle: null };

  // Try "bitcoin/bitcoin#12345" format
  let prRef = null;
  const refMatch = text.match(/([\w.-]+\/[\w.-]+)#(\d+)/);
  if (refMatch) {
    prRef = `${refMatch[1]}#${refMatch[2]}`;
    return {
      prRef,
      prUrl: `https://github.com/${refMatch[1]}/pull/${refMatch[2]}`,
      prTitle: null,
    };
  }

  // Try standalone PR mention
  const prNumMatch = text.match(/PR\s*#?(\d+)/i);
  if (prNumMatch) {
    return {
      prRef: `#${prNumMatch[1]}`,
      prUrl: null,
      prTitle: null,
    };
  }

  return { prRef: null, prUrl: null, prTitle: null };
}

function formatTimestamp(unixSeconds) {
  if (!unixSeconds) return "Unknown";
  const d = new Date(unixSeconds * 1000);
  return d.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }) + " UTC";
}

function formatDateShort(unixSeconds) {
  if (!unixSeconds) return "?";
  const d = new Date(unixSeconds * 1000);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
}

// Parse kind 1 note → basic run info
function parseRunFromKind1(event) {
  const text = event.content || "";
  const blossomUrl = extractBlossomUrl(text);
  if (!blossomUrl) return null;

  const workshopMatch = text.match(/workshop\s*#?(\d+)/i);
  const prInfo = extractPRInfo(text);
  const prTitleMatch = text.match(/^[^\n]{10,120}/m);

  return {
    id: event.id,
    eventId: event.id,
    kind: 1,
    workshopId: workshopMatch ? workshopMatch[1] : "?",
    prTitle: prInfo.prTitle || (prTitleMatch ? prTitleMatch[0].trim() : text.slice(0, 80)),
    prRef: prInfo.prRef,
    prUrl: prInfo.prUrl,
    mode: "augmented", // default assumption for kind 1
    modeSource: "guessed",
    status: "success",
    blossomUrl,
    blossomHash: blossomUrl.split("/").pop(),
    timestamp: event.created_at,
    questions: null,
    duration: null,
    host: null,
    author: null,
    content: text,
    rawEvent: event,
  };
}

// Parse kind 6500 DVM result → rich run info
function parseRunFromKind6500(event) {
  const tags = event.tags || [];
  const text = event.content || "";

  const status = getTag(tags, "status") || "success";
  const workshopId = getParam(tags, "workshop_id") || getParam(tags, "workshop");
  const mode = getParam(tags, "mode") || "augmented";
  const questions = getParam(tags, "questions") || getParam(tags, "questions_answered");
  const duration = getParam(tags, "duration") || getParam(tags, "total_time");
  const host = getParam(tags, "host");
  const author = getParam(tags, "author");
  const prInfo = extractPRInfo(text);

  // Blossom URL from content or output tag
  let blossomUrl = extractBlossomUrl(text);
  if (!blossomUrl) {
    const outputTag = tags.find((t) => t[0] === "output" && t[1] === "blossom");
    if (outputTag && outputTag[2]) blossomUrl = outputTag[2];
  }
  if (!blossomUrl) {
    const urlTag = tags.find((t) => t[0] === "url");
    if (urlTag && urlTag[1]) blossomUrl = urlTag[1];
  }

  // Try to get PR title from content
  let prTitle = prInfo.prTitle;
  if (!prTitle) {
    const titleMatch = text.match(/(?:PR|Pull Request)[:\s]+(.+?)(?:\n|$)/i);
    if (titleMatch) prTitle = titleMatch[1].trim();
  }
  if (!prTitle) prTitle = text.slice(0, 100);

  return {
    id: event.id,
    eventId: event.id,
    kind: 6500,
    workshopId: workshopId || "?",
    prTitle,
    prRef: prInfo.prRef,
    prUrl: prInfo.prUrl,
    mode: mode.toLowerCase(),
    modeSource: "dvm",
    status,
    blossomUrl,
    blossomHash: blossomUrl ? blossomUrl.split("/").pop() : null,
    timestamp: event.created_at,
    questions,
    duration,
    host,
    author,
    content: text,
    rawEvent: event,
  };
}

function mergeRuns(events) {
  const parsed = [];

  for (const evt of events) {
    let run = null;
    if (evt.kind === 6500) {
      run = parseRunFromKind6500(evt);
    } else if (evt.kind === 1) {
      run = parseRunFromKind1(evt);
    }
    if (run) parsed.push(run);
  }

  const workshops = new Map();

  for (const run of parsed) {
    const key = run.workshopId;
    if (!workshops.has(key)) {
      workshops.set(key, {
        workshopId: key,
        modes: {},
        timestamp: 0,
        prTitle: run.prTitle,
        prRef: run.prRef,
        prUrl: run.prUrl,
        host: null,
        author: null,
        questions: null,
        duration: null,
        status: "success",
      });
    }
    const ws = workshops.get(key);

    if (run.blossomUrl) {
      ws.modes[run.mode] = {
        blossomUrl: run.blossomUrl,
        blossomHash: run.blossomHash,
        eventId: run.eventId,
        timestamp: run.timestamp,
        kind: run.kind,
        content: run.content,
      };
    }

    if (run.kind === 6500) {
      ws.host = run.host || ws.host;
      ws.author = run.author || ws.author;
      ws.questions = run.questions || ws.questions;
      ws.duration = run.duration || ws.duration;
      ws.prTitle = run.prTitle || ws.prTitle;
      ws.prRef = run.prRef || ws.prRef;
      ws.prUrl = run.prUrl || ws.prUrl;
    }

    if (run.mode === "augmented" && run.prTitle) ws.prTitle = run.prTitle;
    if (run.timestamp > ws.timestamp) ws.timestamp = run.timestamp;
    if (run.status === "error") ws.status = "error";
  }

  return [...workshops.values()].sort((a, b) => b.timestamp - a.timestamp);
}

// =========================================================================
// Blossom: Fetch report content
// =========================================================================

async function fetchReport(blossomUrl) {
  const resp = await fetch(blossomUrl);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return await resp.text();
}

// =========================================================================
// Rendering
// =========================================================================

function updateConnectionStatus(connected, total) {
  const el = document.getElementById("conn-status");
  if (!el) return;
  if (connected === 0) {
    el.textContent = "Offline";
    el.className = "conn-badge offline";
  } else if (connected < total) {
    el.textContent = `${connected}/${total} relays`;
    el.className = "conn-badge partial";
  } else {
    el.textContent = `${connected}/${total} relays`;
    el.className = "conn-badge online";
  }
}

function modeBadge(mode) {
  const cls = mode === "blind" ? "mode-blind" : "mode-augmented";
  const label = mode === "blind" ? "BLIND" : "AUGMENTED";
  return `<span class="mode-badge ${cls}">${label}</span>`;
}

function statusIcon(status) {
  if (status === "success") return `<span class="status-dot status-success" title="Success"></span>`;
  if (status === "partial") return `<span class="status-dot status-partial" title="Partial"></span>`;
  if (status === "error") return `<span class="status-dot status-error" title="Error"></span>`;
  return "";
}

function renderRunsList(runs) {
  const container = document.getElementById("runs-list");
  container.innerHTML = "";

  if (runs.length === 0) {
    container.innerHTML = `
      <div class="runs-empty">
        <div class="runs-empty-icon">⚠</div>
        <p>No workshop runs found from the bot.</p>
        <p class="hint">Make sure the agent has published<br>kind 1 or kind 6500 events.</p>
      </div>`;
    return;
  }

  const countEl = document.createElement("div");
  countEl.className = "runs-count";
  countEl.textContent = `${runs.length} workshop${runs.length !== 1 ? "s" : ""}`;
  container.appendChild(countEl);

  runs.forEach((ws) => {
    const card = document.createElement("div");
    card.className = "run-card";
    card.dataset.workshopId = ws.workshopId;
    if (ws.workshopId === selectedWorkshopId) card.classList.add("active");

    const modeKeys = Object.keys(ws.modes);
    const modeBadges = modeKeys.map(m => modeBadge(m)).join(" ");

    card.innerHTML = `
      <div class="run-card-header">
        <span class="workshop-id">#${escapeHtml(ws.workshopId)}</span>
        <div class="mode-badges">${modeBadges}</div>
      </div>
      <div class="pr-title">${escapeHtml(ws.prTitle)}</div>
      <div class="run-card-footer">
        ${statusIcon(ws.status)}
        <span class="timestamp">${escapeHtml(formatDateShort(ws.timestamp))}</span>
      </div>
    `;

    card.addEventListener("click", () => {
      selectWorkshop(ws);
      if (window.innerWidth <= 768) {
        document.getElementById("app").classList.remove("sidebar-open");
      }
    });

    container.appendChild(card);
  });
}

let selectedWorkshopId = null;
let currentWorkshop = null;
let currentMode = null;

async function selectWorkshop(ws, forceMode = null) {
  selectedWorkshopId = ws.workshopId;
  currentWorkshop = ws;
  document.querySelectorAll(".run-card").forEach((el) => {
    el.classList.toggle("active", el.dataset.workshopId === ws.workshopId);
  });

  const availableModes = Object.keys(ws.modes);
  const preferMode = forceMode || (availableModes.includes("augmented") ? "augmented" : availableModes[0]);
  currentMode = preferMode;
  const modeData = ws.modes[preferMode];
  const hasBoth = availableModes.length > 1;

  const view = document.getElementById("report-view");

  const toggleHtml = hasBoth
    ? `<div class="mode-toggle">
         ${availableModes.map(m => `<button class="mode-btn ${m === preferMode ? "active" : ""}" data-mode="${m}">${m.toUpperCase()}</button>`).join("")}
       </div>`
    : `<div class="mode-toggle-single">${modeBadge(preferMode)}</div>`;

  view.innerHTML = `
    <div class="detail-header">
      <div class="detail-header-top">
        <div class="detail-titles">
          <div class="detail-workshop">
            <span class="workshop-id-lg">Workshop #${escapeHtml(ws.workshopId)}</span>
            ${statusIcon(ws.status)}
          </div>
          <h2 class="detail-pr-title">${escapeHtml(ws.prTitle)}</h2>
        </div>
      </div>
      ${toggleHtml}
      <div class="detail-meta-grid">
        ${ws.prRef ? `<div class="meta-item"><span class="meta-label">PR</span><span class="meta-value">${escapeHtml(ws.prRef)}</span></div>` : ""}
        ${ws.host ? `<div class="meta-item"><span class="meta-label">Host</span><span class="meta-value">${escapeHtml(ws.host)}</span></div>` : ""}
        ${ws.author ? `<div class="meta-item"><span class="meta-label">Author</span><span class="meta-value">${escapeHtml(ws.author)}</span></div>` : ""}
        <div class="meta-item"><span class="meta-label">Date</span><span class="meta-value">${escapeHtml(formatTimestamp(ws.timestamp))}</span></div>
      </div>
      <div class="detail-metrics">
        ${ws.questions ? `<div class="metric"><span class="metric-value">${escapeHtml(ws.questions)}</span><span class="metric-label">Questions</span></div>` : ""}
        ${ws.duration ? `<div class="metric"><span class="metric-value">${escapeHtml(ws.duration)}</span><span class="metric-label">Duration</span></div>` : ""}
        <div class="metric"><span class="metric-value">${availableModes.join(" / ")}</span><span class="metric-label">Mode${availableModes.length > 1 ? "s" : ""}</span></div>
      </div>
      <div class="detail-links">
        ${modeData?.blossomUrl ? `<a href="${modeData.blossomUrl}" target="_blank" class="detail-link">Blossom ↗</a>` : ""}
        ${modeData?.eventId ? `<a href="https://njump.me/${modeData.eventId}" target="_blank" class="detail-link">Nostr ↗</a>` : ""}
        ${ws.prUrl ? `<a href="${ws.prUrl}" target="_blank" class="detail-link">GitHub PR ↗</a>` : ""}
      </div>
    </div>
    <div class="report-content">
      <div class="report-loading">
        <div class="spinner"></div>
        <p>Fetching ${preferMode} report from Blossom…</p>
      </div>
    </div>
  `;

  if (hasBoth) {
    view.querySelectorAll(".mode-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const newMode = btn.dataset.mode;
        if (newMode !== currentMode) {
          selectWorkshop(currentWorkshop, newMode);
        }
      });
    });
  }

  const contentEl = view.querySelector(".report-content");
  const blossomUrl = modeData?.blossomUrl;

  if (!blossomUrl) {
    contentEl.innerHTML = `<div class="report-error"><p>No ${preferMode} report URL found.</p></div>`;
    return;
  }

  try {
    const reportText = await fetchReport(blossomUrl);
    contentEl.innerHTML = `<pre>${escapeHtml(reportText)}</pre>`;
  } catch (e) {
    contentEl.innerHTML = `
      <div class="report-error">
        <div class="error-icon">✕</div>
        <p>Failed to fetch report</p>
        <p class="error-detail">${escapeHtml(e.message)}</p>
      </div>`;
  }
}

function showGlobalError(message) {
  const container = document.getElementById("runs-list");
  container.innerHTML = `
    <div class="runs-empty">
      <div class="runs-empty-icon">⚠</div>
      <p>${escapeHtml(message)}</p>
      <p class="hint">Check your connection and try<br>refreshing the page.</p>
    </div>`;
}

function escapeHtml(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// =========================================================================
// Init
// =========================================================================

(async function init() {
  console.log("[BCR Agent] Initializing…");
  console.log("[BCR Agent] Relays:", RELAYS);
  console.log("[BCR Agent] Bot npub (hex):", BOT_NPUB_HEX);
  console.log("[BCR Agent] Fetching kinds [1, 6500]");

  // Mobile sidebar toggle
  const menuBtn = document.getElementById("menu-toggle");
  const backdrop = document.getElementById("sidebar-backdrop");
  const app = document.getElementById("app");

  if (menuBtn) {
    menuBtn.addEventListener("click", () => {
      app.classList.toggle("sidebar-open");
    });
  }
  if (backdrop) {
    backdrop.addEventListener("click", () => {
      app.classList.remove("sidebar-open");
    });
  }

  const loadingEl = document.getElementById("runs-loading");
  if (loadingEl) {
    loadingEl.innerHTML = `
      <div class="connecting">
        <div class="spinner"></div>
        <p>Connecting to relays…</p>
        <div class="relay-list">${RELAYS.map((r) => `<span class="relay-chip">${r.replace("wss://", "")}</span>`).join("")}</div>
      </div>`;
  }

  try {
    const { events, connected } = await fetchNostrEvents(BOT_NPUB_HEX, [1, 6500], 50);

    const kind1Count = events.filter((e) => e.kind === 1).length;
    const kind6500Count = events.filter((e) => e.kind === 6500).length;
    console.log(`[BCR Agent] Connected to ${connected}/${RELAYS.length} relays`);
    console.log(`[BCR Agent] Received ${events.length} events (kind 1: ${kind1Count}, kind 6500: ${kind6500Count})`);

    allRuns = mergeRuns(events);
    console.log(`[BCR Agent] Parsed ${allRuns.length} workshop runs`);

    if (connected === 0 && events.length === 0) {
      showGlobalError("Could not connect to any relay.");
      return;
    }

    renderRunsList(allRuns);

    if (allRuns.length > 0) {
      selectWorkshop(allRuns[0]);
    }
  } catch (e) {
    console.error("[BCR Agent] Init error:", e);
    showGlobalError(`Initialization failed: ${e.message}`);
  }
})();
