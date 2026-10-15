// Клиентская логика для ChatGPT Chat Exporter Web UI

let currentExportData = null;
let isRawView = false;

document.addEventListener("DOMContentLoaded", () => {
  const exportBtn = document.getElementById("exportBtn");
  const pasteBtn = document.getElementById("pasteBtn");
  const urlInput = document.getElementById("urlInput");
  const downloadBtn = document.getElementById("downloadBtn");
  const copyBtn = document.getElementById("copyBtn");
  const toggleViewBtn = document.getElementById("toggleViewBtn");

  exportBtn.addEventListener("click", handleExport);
  pasteBtn.addEventListener("click", handlePaste);
  downloadBtn.addEventListener("click", handleDownload);
  copyBtn.addEventListener("click", handleCopy);
  toggleViewBtn.addEventListener("click", handleToggleView);

  urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      handleExport();
    }
  });
});

async function handlePaste() {
  const urlInput = document.getElementById("urlInput");
  try {
    const text = await navigator.clipboard.readText();
    if (text) {
      urlInput.value = text.trim();
      urlInput.focus();
    }
  } catch (err) {
    // В некоторых браузерах может потребоваться разрешение пользователя
    urlInput.focus();
    alert("Нажмите Cmd+V / Ctrl+V для вставки ссылки из буфера.");
  }
}

async function handleExport() {
  const urlInput = document.getElementById("urlInput");
  const url = urlInput.value.trim();

  if (!url) {
    showStatus("error", "Пожалуйста, вставьте ссылку на чат ChatGPT.");
    urlInput.focus();
    return;
  }

  const includeHeader = document.getElementById("optHeader").checked;
  const includeTimestamps = document.getElementById("optTime").checked;

  showStatus("loading", "Загрузка и парсинг чата с ChatGPT...");
  setButtonsBusy(true);

  // Определяем эндпоинт API:
  // Если страница открыта локально или на Vercel/Render/Railway — используем /api
  const apiEndpoint = "/api";

  try {
    const resp = await fetch(apiEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: url,
        include_header: includeHeader,
        include_timestamps: includeTimestamps,
      }),
    });

    const data = await resp.json();

    if (!resp.ok || !data.success) {
      throw new Error(data.error || `Ошибка сервера: HTTP ${resp.status}`);
    }

    currentExportData = data;
    hideStatus();
    renderResult(data);
  } catch (err) {
    showStatus(
      "error",
      `Не удалось экспортировать: ${err.message}`
    );
  } finally {
    setButtonsBusy(false);
  }
}

function renderResult(data) {
  const resultCard = document.getElementById("resultCard");
  const resTitle = document.getElementById("resTitle");
  const resModelBadge = document.getElementById("resModelBadge");
  const resMsgCount = document.getElementById("resMsgCount");
  const chatView = document.getElementById("chatView");
  const rawTxtContent = document.getElementById("rawTxtContent");

  resTitle.textContent = data.title || "Чат ChatGPT";
  resModelBadge.textContent = data.model_name || "GPT";
  resMsgCount.textContent = `Сообщений: ${data.messages ? data.messages.length : 0}`;

  // Рендерим облачки чата
  chatView.innerHTML = "";
  if (data.messages && data.messages.length > 0) {
    data.messages.forEach((msg) => {
      const bubble = document.createElement("div");
      bubble.className = `message-bubble ${msg.role === "user" ? "user" : "assistant"}`;

      const meta = document.createElement("div");
      meta.className = "bubble-meta";
      meta.innerHTML = `<span>${escapeHtml(msg.role_label || msg.role)}</span><span>${escapeHtml(msg.datetime_str || "")}</span>`;

      const content = document.createElement("div");
      content.className = "bubble-content";
      content.textContent = msg.text;

      bubble.appendChild(meta);
      bubble.appendChild(content);
      chatView.appendChild(bubble);
    });
  }

  // Заполняем сырой текст
  rawTxtContent.textContent = data.txt_content || "";

  // Показываем блок результатов
  resultCard.style.display = "block";
  resultCard.scrollIntoView({ behavior: "smooth", block: "start" });
}

function handleDownload() {
  if (!currentExportData || !currentExportData.txt_content) return;

  const filename = currentExportData.filename || "chatgpt_export.txt";
  const blob = new Blob([currentExportData.txt_content], {
    type: "text/plain;charset=utf-8",
  });

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function handleCopy() {
  if (!currentExportData || !currentExportData.txt_content) return;

  navigator.clipboard.writeText(currentExportData.txt_content).then(() => {
    const copyBtn = document.getElementById("copyBtn");
    const originalText = copyBtn.innerHTML;
    copyBtn.innerHTML = "✅ Скопировано!";
    setTimeout(() => {
      copyBtn.innerHTML = originalText;
    }, 2000);
  });
}

function handleToggleView() {
  const chatView = document.getElementById("chatView");
  const rawView = document.getElementById("rawView");
  const toggleBtn = document.getElementById("toggleViewBtn");

  isRawView = !isRawView;
  if (isRawView) {
    chatView.style.display = "none";
    rawView.style.display = "block";
    toggleBtn.textContent = "💬 Вид чата";
  } else {
    chatView.style.display = "flex";
    rawView.style.display = "none";
    toggleBtn.textContent = "📝 Исходный .txt";
  }
}

function showStatus(type, message) {
  const box = document.getElementById("statusBox");
  box.style.display = "flex";
  if (type === "loading") {
    box.className = "status-box loading";
    box.innerHTML = `<div class="spinner"></div><span>${escapeHtml(message)}</span>`;
  } else {
    box.className = "status-box error";
    box.innerHTML = `<span>❌ ${escapeHtml(message)}</span>`;
  }
}

function hideStatus() {
  const box = document.getElementById("statusBox");
  box.style.display = "none";
}

function setButtonsBusy(busy) {
  const exportBtn = document.getElementById("exportBtn");
  const pasteBtn = document.getElementById("pasteBtn");
  exportBtn.disabled = busy;
  pasteBtn.disabled = busy;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
