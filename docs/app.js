// BCR Agent — Nostr client for GitHub Pages
// Fetches kind 1 notes from the bot npub, parses Blossom URLs, renders reports.
// Pure vanilla JS, no dependencies, no build step.

const BOT_NPUB_HEX = "9a515b0f08d554b582e54202c7ca0e6ee56d81559957cbf9b40047d391b95fd5";
const RELAYS = [
  "wss://nos.lol",
  "wss://relay.damus.io",
];
const BLOSSOM_SERVER = "https://blossom.psbt.me";

// --- Nostr relay fetching via raw WebSocket ---

function fetchNostrEvents(pubkeyHex, kinds = [1], limit = 20) {
  return new Promise((resolve) => {
    const events = [];
    let resolved = false;
    let connectedRelays = 0;

    const timeout = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        resolve(events);
      }
    }, 8000);

    RELAYS.forEach((relayUrl) => {
      let ws;
      try {
        ws = new WebSocket(relayUrl);
      } catch (e) {
        connectedRelays++;
        checkDone();
        return;
      }

      const subId = "bcr-" + Math.random().toString(36).slice(2, 8);

      ws.onopen = () => {
        ws.send(JSON.stringify([
          "REQ", subId,
          { authors: [pubkeyHex], kinds, limit, since: Math.floor(Date.now() / 1000) - 86400 * 90 }
        ]));
      };

      ws.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data);
          if (data[0] === "EVENT" && data[1] === subId && data[2]) {
            const evt = data[2];
            if (!events.find(e => e.id === evt.id)) {
              events.push(evt);
            }
          } else if (data[0] === "EOSE" && data[1] === subId) {
            ws.send(JSON.stringify(["CLOSE", subId]));
            ws.close();
            connectedRelays++;
            checkDone();
          }
        } catch (e) { /* ignore parse errors */ }
      };

      ws.onerror = () => {
        connectedRelays++;
        checkDone();
      };

      ws.onclose = () => {
        connectedRelays++;
        checkDone();
      };
    });

    function checkDone() {
      if (connectedRelays >= RELAYS.length && !resolved) {
        clearTimeout(timeout);
        resolved = true;
        resolve(events);
      }
    }
  });
}

// --- Parse kind 1 notes to extract BCR runs ---

function parseRunFromNote(note) {
  const text = note.content || "";

  const workshopMatch = text.match(/workshop #(\d+)/i);
  const urlMatch = text.match(/(https:\/\/blossom\.psbt\.me\/[a-f0-9]+)/i);
  const prMatch = text.match(/\(([^)]+)\)/);

  if (!urlMatch) return null;

  return {
    eventId: note.id,
    workshopId: workshopMatch ? workshopMatch[1] : "?",
    prTitle: prMatch ? prMatch[1] : text.slice(0, 80) + "...",
    blossomUrl: urlMatch[1],
    blossomHash: urlMatch[1].split("/").pop(),
    timestamp: note.created_at,
    timestampStr: new Date(note.created_at * 1000).toLocaleString("en-US", {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", timeZone: "UTC"
    }) + " UTC",
    rawNote: note,
  };
}

// --- Fetch report from Blossom ---

async function fetchReport(blossomUrl) {
  const resp = await fetch(blossomUrl);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return await resp.text();
}

// --- Rendering ---

function renderRunsList(runs) {
  const container = document.getElementById("runs-list");
  container.innerHTML = "";

  if (runs.length === 0) {
    container.innerHTML = '<div class="loading">No BCR runs found from the bot npub.<br>Make sure the agent has published results.</div>';
    return;
  }

  runs.forEach((run) => {
    const card = document.createElement("div");
    card.className = "run-card";
    card.dataset.eventId = run.eventId;

    card.innerHTML = `
      <div class="workshop-id">Workshop #${run.workshopId}</div>
      <div class="pr-title">${escapeHtml(run.prTitle)}</div>
      <div class="timestamp">${run.timestampStr}</div>
    `;

    card.addEventListener("click", () => selectRun(run, card));
    container.appendChild(card);
  });

  if (runs.length > 0) {
    const firstCard = container.querySelector(".run-card");
    if (firstCard) firstCard.click();
  }
}

async function selectRun(run, cardEl) {
  document.querySelectorAll(".run-card.active").forEach(el => el.classList.remove("active"));
  cardEl.classList.add("active");

  const view = document.getElementById("report-view");
  view.innerHTML = '<div class="loading">Fetching report from Blossom…</div>';

  try {
    const reportText = await fetchReport(run.blossomUrl);

    view.innerHTML = `
      <div class="report-meta">
        <span class="badge">AUGMENTED</span>
        <span>Workshop #${run.workshopId}</span>
        <span>${run.timestampStr}</span>
        <a href="${run.blossomUrl}" target="_blank">Blossom ↗</a>
        <a href="https://njump.me/${run.eventId}" target="_blank">Nostr ↗</a>
      </div>
      <div class="report-content">
        <pre>${escapeHtml(reportText)}</pre>
      </div>
    `;
  } catch (e) {
    view.innerHTML = `<div class="empty-state"><p>Failed to fetch report: ${escapeHtml(e.message)}</p></div>`;
  }
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// --- Init ---

(async function init() {
  console.log("BCR Agent: fetching notes from", RELAYS);
  console.log("BCR Agent: bot npub (hex):", BOT_NPUB_HEX);

  const notes = await fetchNostrEvents(BOT_NPUB_HEX, [1], 20);

  const runs = notes
    .map(parseRunFromNote)
    .filter(r => r !== null)
    .sort((a, b) => b.timestamp - a.timestamp);

  console.log(`BCR Agent: found ${notes.length} notes, ${runs.length} BCR runs`);

  renderRunsList(runs);
})();
