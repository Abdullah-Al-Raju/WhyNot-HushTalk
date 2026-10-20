/**
 * WhyNot-HushTalk Web Client Application
 * Author: Abduallah Al Raju
 */

const state = {
  status: {},
  messages: [],
  packets: [],
  iats: [],
  ws: null,
};

// DOM Elements
const chatMessagesEl = document.getElementById("chat-messages");
const emptyStateEl = document.getElementById("empty-state");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const btnSend = document.getElementById("btn-send");
const charCount = document.getElementById("char-count");
const timingEstimate = document.getElementById("timing-estimate");
const packetFeed = document.getElementById("packet-feed");

// Indicators
const valTransport = document.getElementById("val-transport");
const valProfile = document.getElementById("val-profile");
const valKey = document.getElementById("val-key");
const valStatus = document.getElementById("val-status");
const displayTarget = document.getElementById("display-target");

// Telemetry
const statSamples = document.getElementById("stat-samples");
const statMean = document.getElementById("stat-mean");
const statStd = document.getElementById("stat-std");
const statCov = document.getElementById("stat-cov");
const canvas = document.getElementById("iat-canvas");
const ctx = canvas.getContext("2d");

// Modal
const configModal = document.getElementById("config-modal");
const btnOpenConfig = document.getElementById("btn-open-config");
const btnCloseModal = document.getElementById("btn-close-modal");
const btnCancelModal = document.getElementById("btn-cancel-modal");
const configForm = document.getElementById("config-form");

// Connect WebSocket
function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;
  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    valStatus.textContent = "ONLINE";
    document.querySelector(".status-dot").style.backgroundColor = "var(--accent-emerald)";
  };

  ws.onclose = () => {
    valStatus.textContent = "DISCONNECTED";
    document.querySelector(".status-dot").style.backgroundColor = "var(--accent-rose)";
    setTimeout(connectWebSocket, 2000);
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleServerEvent(msg);
    } catch (e) {
      console.error("WS parse error:", e);
    }
  };

  state.ws = ws;
}

// Handle real-time node events
function handleServerEvent(ev) {
  switch (ev.type) {
    case "init":
      updateStatus(ev.status);
      state.messages = ev.messages || [];
      renderAllMessages();
      fetchTelemetry();
      break;

    case "config_updated":
    case "node_started":
      updateStatus(ev.data);
      break;

    case "message_queued":
      addOrUpdateMessage(ev.data);
      break;

    case "message_progress":
    case "message_status":
      addOrUpdateMessage(ev.data);
      break;

    case "message_received":
      addOrUpdateMessage(ev.data);
      fetchTelemetry();
      break;

    case "packet_event":
      addPacketLog(ev.data);
      fetchTelemetry();
      break;
  }
}

function updateStatus(status) {
  state.status = status;
  valTransport.textContent = `${status.transport.toUpperCase()}:${status.port}`;
  valProfile.textContent = status.profile;
  valKey.textContent = status.has_key ? status.key_preview : "UNKEYED";
  displayTarget.textContent = `Peer: ${status.target_ip}:${status.port}`;

  if (status.timing_telemetry) {
    statSamples.textContent = status.timing_telemetry.sample_count;
    statMean.textContent = `${status.timing_telemetry.mean_iat_ms} ms`;
    statStd.textContent = `${status.timing_telemetry.std_dev_ms} ms`;
    statCov.textContent = status.timing_telemetry.cov.toFixed(3);
  }
}

async function fetchTelemetry() {
  try {
    const res = await fetch("/api/telemetry");
    const data = await res.json();
    state.iats = data.inter_arrival_times || [];
    drawHistogram(state.iats);
  } catch (err) {
    console.error("Telemetry fetch error:", err);
  }
}

// Render Messages
function renderAllMessages() {
  chatMessagesEl.innerHTML = "";
  if (state.messages.length === 0) {
    chatMessagesEl.appendChild(emptyStateEl);
    emptyStateEl.style.display = "block";
    return;
  }
  emptyStateEl.style.display = "none";
  state.messages.forEach((m) => renderSingleMessage(m));
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

function addOrUpdateMessage(msg) {
  emptyStateEl.style.display = "none";
  const existingIdx = state.messages.findIndex((m) => m.id === msg.id);
  if (existingIdx >= 0) {
    state.messages[existingIdx] = msg;
    const existingNode = document.getElementById(`msg-${msg.id}`);
    if (existingNode) {
      existingNode.outerHTML = createMessageHTML(msg);
    }
  } else {
    state.messages.push(msg);
    renderSingleMessage(msg);
  }
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
}

function renderSingleMessage(msg) {
  const div = document.createElement("div");
  div.innerHTML = createMessageHTML(msg);
  chatMessagesEl.appendChild(div.firstElementChild);
}

function createMessageHTML(msg) {
  const isOut = msg.direction === "outbound";
  const badgeClass = `badge-${msg.status.toLowerCase()}`;
  const pct = Math.round(msg.progress * 100);

  let metaStats = "";
  if (msg.status === "delivered" || msg.status === "acknowledged") {
    metaStats = `Duration: ${(msg.elapsed_ms / 1000).toFixed(1)}s | ${msg.cps.toFixed(1)} c/s`;
    if (msg.avg_jitter_ms) {
      metaStats += ` | Jitter: ±${msg.avg_jitter_ms.toFixed(1)}ms`;
    }
  } else if (msg.status === "transmitting") {
    metaStats = `Modulating symbol ${msg.symbols_sent} / ${msg.symbols_total} (${pct}%)`;
  }

  return `
    <div class="chat-msg ${msg.direction}" id="msg-${msg.id}">
      <div class="msg-header">
        <span class="msg-sender">${isOut ? "LOCAL SENDER" : "REMOTE PEER"}</span>
        <span class="msg-status-badge ${badgeClass}">${msg.status}</span>
      </div>
      <div class="msg-text">${escapeHtml(msg.text)}</div>
      ${
        msg.status === "transmitting"
          ? `<div class="msg-progress-bar"><div class="msg-progress-fill" style="width: ${pct}%"></div></div>`
          : ""
      }
      <div class="msg-footer">
        <span>${metaStats}</span>
        <span>${new Date(msg.timestamp * 1000).toLocaleTimeString()}</span>
      </div>
    </div>
  `;
}

function addPacketLog(pkt) {
  const empty = packetFeed.querySelector(".packet-log-empty");
  if (empty) empty.remove();

  const row = document.createElement("div");
  row.className = `pkt-row ${pkt.dir}`;
  const prefix = pkt.dir === "out" ? "->" : "<-";
  const target = pkt.target || pkt.src || "";
  row.innerHTML = `
    <span>${prefix} [${pkt.proto}]</span>
    <span>seq=${pkt.seq}</span>
    <span>${target}</span>
    <span style="margin-left:auto;">${new Date(pkt.timestamp).toLocaleTimeString().split(" ")[0]}</span>
  `;
  packetFeed.prepend(row);
  if (packetFeed.children.length > 50) {
    packetFeed.removeChild(packetFeed.lastChild);
  }
}

// Canvas Histogram Drawing
function drawHistogram(samples) {
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  // Background grid
  ctx.strokeStyle = "#1A2436";
  ctx.lineWidth = 1;
  for (let y = 30; y < h; y += 30) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }

  if (!samples || samples.length === 0) {
    ctx.fillStyle = "#64748B";
    ctx.font = "11px monospace";
    ctx.textAlign = "center";
    ctx.fillText("Waiting for timing samples...", w / 2, h / 2);
    return;
  }

  // Create 30 histogram bins from 0ms to 2500ms
  const binCount = 30;
  const maxDelay = 2500;
  const bins = new Array(binCount).fill(0);

  samples.forEach((val) => {
    const idx = Math.min(binCount - 1, Math.floor((val / maxDelay) * binCount));
    bins[idx]++;
  });

  const maxFreq = Math.max(...bins, 1);
  const barWidth = (w - 20) / binCount;

  bins.forEach((freq, i) => {
    const barHeight = (freq / maxFreq) * (h - 40);
    const x = 10 + i * barWidth;
    const y = h - 20 - barHeight;

    // Gradient bar
    const grad = ctx.createLinearGradient(0, y, 0, h - 20);
    grad.addColorStop(0, "#06B6D4");
    grad.addColorStop(1, "rgba(6, 182, 212, 0.2)");

    ctx.fillStyle = grad;
    ctx.fillRect(x, y, barWidth - 2, barHeight);
  });

  // Axis labels
  ctx.fillStyle = "#64748B";
  ctx.font = "10px monospace";
  ctx.textAlign = "left";
  ctx.fillText("0ms", 10, h - 6);
  ctx.textAlign = "center";
  ctx.fillText("1250ms", w / 2, h - 6);
  ctx.textAlign = "right";
  ctx.fillText("2500ms", w - 10, h - 6);
}

// Chat Form Submission
chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = "";
  updateTimingEstimate("");

  try {
    const res = await fetch("/api/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();
    if (data.error) {
      alert("Error: " + data.error);
    }
  } catch (err) {
    console.error("Send error:", err);
  }
});

// Quick chips
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    chatInput.value = chip.getAttribute("data-text");
    updateTimingEstimate(chatInput.value);
    chatInput.focus();
  });
});

chatInput.addEventListener("input", () => {
  updateTimingEstimate(chatInput.value);
});

function updateTimingEstimate(text) {
  const len = text.length;
  charCount.textContent = `${len} / 800 chars`;
  const baseRate = state.status.profile === "fast" ? 0.4 : 2.5;
  const sec = (len * baseRate).toFixed(1);
  timingEstimate.textContent = `Estimated transmit time: ~${sec}s`;
}

// Config Modal
btnOpenConfig.addEventListener("click", () => {
  const s = state.status;
  document.getElementById("cfg-target").value = s.target_ip || "127.0.0.1";
  document.getElementById("cfg-transport").value = s.transport || "udp";
  document.getElementById("cfg-port").value = s.port || 9999;
  document.getElementById("cfg-listen-port").value = s.listen_port || s.port || 9999;
  document.getElementById("cfg-key").value = state.key || "";
  document.getElementById("cfg-profile").value = s.profile || "fast";
  document.getElementById("cfg-payload").value = s.payload_style || "pattern";
  document.getElementById("cfg-auto-ack").checked = s.auto_ack !== false;
  configModal.classList.remove("hidden");
});

function closeModal() {
  configModal.classList.add("hidden");
}

btnCloseModal.addEventListener("click", closeModal);
btnCancelModal.addEventListener("click", closeModal);

configForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    target_ip: document.getElementById("cfg-target").value.trim(),
    transport: document.getElementById("cfg-transport").value,
    port: parseInt(document.getElementById("cfg-port").value, 10),
    listen_port: parseInt(document.getElementById("cfg-listen-port").value, 10),
    key: document.getElementById("cfg-key").value.trim(),
    profile: document.getElementById("cfg-profile").value,
    payload_style: document.getElementById("cfg-payload").value,
    auto_ack: document.getElementById("cfg-auto-ack").checked,
  };

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data.status === "success") {
      updateStatus(data.config);
      closeModal();
    }
  } catch (err) {
    alert("Config error: " + err);
  }
});

function escapeHtml(str) {
  return str.replace(/[&<>'"]/g, (tag) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[tag] || tag));
}

// Initialize
connectWebSocket();
drawHistogram([]);
