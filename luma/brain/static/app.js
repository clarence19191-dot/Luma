const state = {
  consoleSocket: null,
  emotion: "idle",
  emotions: [],
  metadataRefreshAt: 0,
};

const els = {
  robot: document.getElementById("robot"),
  screen: document.getElementById("screen"),
  speechBubble: document.getElementById("speechBubble"),
  deviceState: document.getElementById("deviceState"),
  emotionState: document.getElementById("emotionState"),
  voiceState: document.getElementById("voiceState"),
  conversationState: document.getElementById("conversationState"),
  toneState: document.getElementById("toneState"),
  behaviorState: document.getElementById("behaviorState"),
  boundaryState: document.getElementById("boundaryState"),
  queueState: document.getElementById("queueState"),
  audioState: document.getElementById("audioState"),
  memoryState: document.getElementById("memoryState"),
  transcriptBox: document.getElementById("transcriptBox"),
  replyText: document.getElementById("replyText"),
  eventLog: document.getElementById("eventLog"),
  commandInput: document.getElementById("commandInput"),
  emotionPalette: document.getElementById("emotionPalette"),
  speechInput: document.getElementById("speechInput"),
  sendBtn: document.getElementById("sendBtn"),
  voiceTextBtn: document.getElementById("voiceTextBtn"),
  wakeBtn: document.getElementById("wakeBtn"),
  cancelVoiceBtn: document.getElementById("cancelVoiceBtn"),
  estopBtn: document.getElementById("estopBtn"),
  resetBtn: document.getElementById("resetBtn"),
  clearLogBtn: document.getElementById("clearLogBtn"),
  resetConversationBtn: document.getElementById("resetConversationBtn"),
  refreshMemoryBtn: document.getElementById("refreshMemoryBtn"),
  boundaryReason: document.getElementById("boundaryReason"),
  conversationTurns: document.getElementById("conversationTurns"),
  memoryList: document.getElementById("memoryList"),
};

function wsUrl(path) {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}

function logEvent(kind, payload) {
  const line = `${new Date().toLocaleTimeString()} ${kind} ${JSON.stringify(payload)}`;
  els.eventLog.textContent = `${line}\n${els.eventLog.textContent}`.slice(0, 16000);
}

function connectConsole() {
  state.consoleSocket = new WebSocket(wsUrl("/ws/console"));
  state.consoleSocket.onmessage = (event) => {
    if (event.data === "pong") return;
    const message = JSON.parse(event.data);
    if (message.type === "state") {
      renderState(message.state);
      scheduleMetadataRefresh();
    }
    logEvent(message.type, message);
  };
  state.consoleSocket.onclose = () => setTimeout(connectConsole, 1000);
}

async function loadEmotionPalette() {
  try {
    const response = await fetch("/api/emotions");
    const payload = await response.json();
    state.emotions = payload.emotions || [];
    renderEmotionPalette();
  } catch (error) {
    logEvent("emotion_catalog_error", String(error));
  }
}

function renderEmotionPalette() {
  els.emotionPalette.textContent = "";
  state.emotions.forEach((item) => {
    const button = document.createElement("button");
    button.className = `emotion-btn group-${item.group || "other"}`;
    button.type = "button";
    button.textContent = item.label || item.emotion;
    button.title = item.asset ? `${item.emotion} / ${item.asset}` : item.emotion;
    button.addEventListener("click", () => {
      sendCommand({ type: "set_emotion", emotion: item.emotion, duration_ms: 3000 });
    });
    els.emotionPalette.appendChild(button);
  });
}

function renderState(nextState) {
  const voice = nextState.voice || {};
  els.deviceState.textContent = nextState.device.connected ? `${nextState.device.role || "device"}` : "offline";
  els.emotionState.textContent = nextState.emotion;
  els.voiceState.textContent = voice.phase || "idle";
  els.conversationState.textContent = voice.conversation_id ? shortId(voice.conversation_id) : "none";
  els.toneState.textContent = voice.tone || "-";
  els.behaviorState.textContent = voice.pet_behavior || "-";
  els.boundaryState.textContent = voice.boundary ? voice.boundary.decision : "-";
  els.queueState.textContent = nextState.device.queue_length;
  els.audioState.textContent = formatBytes(voice.audio_bytes || 0);
  els.memoryState.textContent = String(voice.memory_count || 0);
  els.transcriptBox.textContent = voice.transcript || "Transcript";
  els.replyText.textContent = voice.error ? `${voice.error.code}: ${voice.error.message}` : (voice.reply || "Reply");
  renderEmotion(nextState.emotion);
  renderSpeech(nextState.speech.active ? nextState.speech.text : "");
}

function shortId(value) {
  return String(value).replace(/^conv_/, "").slice(0, 8);
}

function renderEmotion(emotion) {
  state.emotion = emotion || "idle";
  const className = state.emotion.replaceAll("_", "-");
  els.screen.className = `screen emotion-${className}`;
  const preset = state.emotions.find((item) => item.emotion === state.emotion);
  if (preset) {
    els.screen.dataset.asset = preset.asset || "";
    els.screen.dataset.group = preset.group || "";
    const previewAsset = gifPreviewAsset(preset.asset || "");
    els.screen.style.backgroundImage = previewAsset ? `url("${previewAsset}")` : "";
    els.screen.classList.toggle("has-gif", Boolean(previewAsset));
  } else {
    delete els.screen.dataset.asset;
    delete els.screen.dataset.group;
    els.screen.style.backgroundImage = "";
    els.screen.classList.remove("has-gif");
  }
}

function gifPreviewAsset(asset) {
  if (!asset) return "";
  if (asset.endsWith(".qgif")) return `/gif/${asset.slice(0, -5)}.gif`;
  if (asset.endsWith(".gif")) return `/gif/${asset}`;
  return "";
}

function renderSpeech(text) {
  els.speechBubble.textContent = text;
  els.speechBubble.style.opacity = text ? "1" : "0";
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(JSON.stringify(payload));
  return payload;
}

async function fetchJson(path) {
  const response = await fetch(path);
  const payload = await response.json();
  if (!response.ok) throw new Error(JSON.stringify(payload));
  return payload;
}

async function sendCommand(command) {
  try {
    const result = await postJson("/api/command", command);
    logEvent("queued", result);
  } catch (error) {
    logEvent("send_error", String(error));
  }
}

async function sendVoiceText() {
  try {
    const result = await postJson("/api/voice/text", { text: els.speechInput.value });
    logEvent("voice_text", result);
    scheduleMetadataRefresh(true);
  } catch (error) {
    logEvent("voice_text_error", String(error));
  }
}

async function wakeVoice() {
  try {
    const result = await postJson("/api/voice/wake", { source: "console", wake_phrase: "你好 Luma" });
    logEvent("wake", result);
  } catch (error) {
    logEvent("wake_error", String(error));
  }
}

async function cancelVoice() {
  try {
    const result = await postJson("/api/voice/cancel", {});
    logEvent("voice_cancel", result);
    scheduleMetadataRefresh(true);
  } catch (error) {
    logEvent("voice_cancel_error", String(error));
  }
}

function scheduleMetadataRefresh(force = false) {
  const now = Date.now();
  if (!force && now - state.metadataRefreshAt < 900) return;
  state.metadataRefreshAt = now;
  refreshConversation().catch((error) => logEvent("conversation_refresh_error", String(error)));
  refreshMemories().catch((error) => logEvent("memory_refresh_error", String(error)));
}

async function refreshConversation() {
  const payload = await fetchJson("/api/conversation");
  renderConversation(payload);
}

async function refreshMemories() {
  const payload = await fetchJson("/api/memories");
  renderMemories(payload.memories || []);
}

function renderConversation(payload) {
  const conversation = payload.conversation || {};
  const boundary = payload.boundary || {};
  const turns = payload.recent_turns || [];
  els.conversationState.textContent = conversation.id ? shortId(conversation.id) : "none";
  els.boundaryState.textContent = boundary.decision || "-";
  const gap = typeof boundary.gap_seconds === "number" ? `${boundary.gap_seconds.toFixed(0)}s` : "-";
  els.boundaryReason.textContent = boundary.reason ? `${boundary.decision || "new"} / ${boundary.reason} / gap ${gap}` : "No boundary yet";
  els.conversationTurns.textContent = "";
  turns.slice(-6).forEach((turn) => {
    const item = document.createElement("div");
    item.className = "turn-item";
    item.innerHTML = `<b>U</b><span></span><b>L</b><span></span>`;
    item.children[1].textContent = turn.user_text || "";
    item.children[3].textContent = turn.luma_text || "";
    els.conversationTurns.appendChild(item);
  });
}

function renderMemories(memories) {
  els.memoryState.textContent = String(memories.length);
  els.memoryList.textContent = "";
  if (!memories.length) {
    const empty = document.createElement("div");
    empty.className = "empty-text";
    empty.textContent = "No active memories";
    els.memoryList.appendChild(empty);
    return;
  }
  memories.forEach((memory) => {
    const item = document.createElement("div");
    item.className = "memory-item";
    const text = document.createElement("div");
    text.innerHTML = `<strong></strong><span></span>`;
    text.querySelector("strong").textContent = memory.type;
    text.querySelector("span").textContent = memory.content;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Delete";
    button.addEventListener("click", async () => {
      await fetch(`/api/memories/${memory.id}`, { method: "DELETE" });
      scheduleMetadataRefresh(true);
    });
    item.appendChild(text);
    item.appendChild(button);
    els.memoryList.appendChild(item);
  });
}

document.querySelectorAll("[data-command]").forEach((button) => {
  button.addEventListener("click", () => sendCommand(JSON.parse(button.dataset.command)));
});

els.sendBtn.addEventListener("click", () => {
  try {
    sendCommand(JSON.parse(els.commandInput.value));
  } catch (error) {
    logEvent("json_error", String(error));
  }
});

els.voiceTextBtn.addEventListener("click", sendVoiceText);
els.wakeBtn.addEventListener("click", wakeVoice);
els.cancelVoiceBtn.addEventListener("click", cancelVoice);

els.estopBtn.addEventListener("click", async () => {
  await postJson("/api/estop", {});
});

els.resetBtn.addEventListener("click", async () => {
  await postJson("/api/reset_estop", {});
});

els.clearLogBtn.addEventListener("click", () => {
  els.eventLog.textContent = "";
});

els.resetConversationBtn.addEventListener("click", async () => {
  try {
    const result = await postJson("/api/conversation/reset", {});
    logEvent("conversation_reset", result);
    scheduleMetadataRefresh(true);
  } catch (error) {
    logEvent("conversation_reset_error", String(error));
  }
});

els.refreshMemoryBtn.addEventListener("click", () => scheduleMetadataRefresh(true));

loadEmotionPalette();
scheduleMetadataRefresh(true);
connectConsole();
