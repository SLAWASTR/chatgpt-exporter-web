// Клиентская логика для ChatGPT Chat Exporter Web UI v2 (PDF, HTML, TXT, Images)

let currentExportData = null;
let isRawView = false;

document.addEventListener("DOMContentLoaded", () => {
  const exportBtn = document.getElementById("exportBtn");
  const pasteBtn = document.getElementById("pasteBtn");
  const urlInput = document.getElementById("urlInput");
  const downloadPdfBtn = document.getElementById("downloadPdfBtn");
  const downloadHtmlBtn = document.getElementById("downloadHtmlBtn");
  const downloadTxtBtn = document.getElementById("downloadTxtBtn");
  const copyBtn = document.getElementById("copyBtn");
  const toggleViewBtn = document.getElementById("toggleViewBtn");

  exportBtn.addEventListener("click", handleExport);
  pasteBtn.addEventListener("click", handlePaste);
  downloadPdfBtn.addEventListener("click", handleDownloadPdf);
  downloadHtmlBtn.addEventListener("click", handleDownloadHtml);
  downloadTxtBtn.addEventListener("click", handleDownloadTxt);
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

  showStatus("loading", "Загрузка, парсинг чата и обработка изображений...");
  setButtonsBusy(true);

  try {
    const resp = await fetch("/api", {
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
  const resImgBadge = document.getElementById("resImgBadge");
  const chatView = document.getElementById("chatView");
  const rawTxtContent = document.getElementById("rawTxtContent");

  resTitle.textContent = data.title || "Чат ChatGPT";
  resModelBadge.textContent = data.model_name || "GPT";
  resMsgCount.textContent = `Сообщений: ${data.messages ? data.messages.length : 0}`;

  // Считаем общее число картинок и вложений
  let totalImages = 0;
  let totalAttachments = 0;
  if (data.messages) {
    data.messages.forEach((m) => {
      if (m.images) totalImages += m.images.length;
      if (m.attachments) totalAttachments += m.attachments.length;
    });
  }

  if (totalImages > 0 || totalAttachments > 0) {
    resImgBadge.style.display = "inline-block";
    resImgBadge.textContent = `🖼️ Фото/картинок: ${totalImages + totalAttachments}`;
  } else {
    resImgBadge.style.display = "none";
  }

  // Рендерим облачки чата
  chatView.innerHTML = "";
  if (data.messages && data.messages.length > 0) {
    data.messages.forEach((msg) => {
      const bubble = document.createElement("div");
      bubble.className = `message-bubble ${msg.role === "user" ? "user" : "assistant"}`;

      const meta = document.createElement("div");
      meta.className = "bubble-meta";
      meta.innerHTML = `<span>${escapeHtml(msg.role_label || msg.role)}</span><span>${escapeHtml(msg.datetime_str || "")}</span>`;
      bubble.appendChild(meta);

      // Если есть прикрепленные пользователем файлы/фото
      if (msg.attachments && msg.attachments.length > 0) {
        msg.attachments.forEach((att) => {
          const attBox = document.createElement("div");
          attBox.className = "attachment-box";
          const dimStr = att.dimensions ? ` • ${escapeHtml(att.dimensions)}` : "";
          attBox.innerHTML = `📷 <strong>${escapeHtml(att.name)}</strong> (${att.size_kb} КБ${dimStr})`;
          bubble.appendChild(attBox);
        });
      }

      // Текст сообщения
      if (msg.text) {
        const content = document.createElement("div");
        content.className = "bubble-content";
        content.textContent = msg.text;
        bubble.appendChild(content);
      }

      // Галерея картинок
      if (msg.images && msg.images.length > 0) {
        const gallery = document.createElement("div");
        gallery.className = "image-gallery";
        msg.images.forEach((imgUrl) => {
          const card = document.createElement("div");
          card.className = "image-card";
          card.innerHTML = `<a href="${imgUrl}" target="_blank" rel="noopener"><img src="${imgUrl}" loading="lazy" alt="Изображение из чата" /></a>`;
          gallery.appendChild(card);
        });
        bubble.appendChild(gallery);
      }

      chatView.appendChild(bubble);
    });
  }

  rawTxtContent.textContent = data.txt_content || "";

  resultCard.style.display = "block";
  resultCard.scrollIntoView({ behavior: "smooth", block: "start" });
}

// Экспорт в PDF через красивый системный диалог печати (A4)
function handleDownloadPdf() {
  if (!currentExportData || !currentExportData.html_content) return;

  const printWindow = window.open("", "_blank");
  if (!printWindow) {
    alert("Разрешите всплывающие окна в браузере, чтобы сохранить PDF.");
    return;
  }

  printWindow.document.write(currentExportData.html_content);
  printWindow.document.close();

  // Даем небольшую паузу для прогрузки стилей и картинок перед вызовом диалога PDF
  setTimeout(() => {
    try {
      printWindow.focus();
      printWindow.print();
    } catch (e) {
      console.error("Print error:", e);
    }
  }, 600);
}

// Скачивание HTML с картинками
function handleDownloadHtml() {
  if (!currentExportData || !currentExportData.html_content) return;

  const filename = currentExportData.filename_html || "chatgpt_context.html";
  const blob = new Blob([currentExportData.html_content], {
    type: "text/html;charset=utf-8",
  });

  triggerBlobDownload(blob, filename);
}

// Скачивание TXT
function handleDownloadTxt() {
  if (!currentExportData || !currentExportData.txt_content) return;

  const filename = currentExportData.filename || "chatgpt_export.txt";
  const blob = new Blob([currentExportData.txt_content], {
    type: "text/plain;charset=utf-8",
  });

  triggerBlobDownload(blob, filename);
}

function triggerBlobDownload(blob, filename) {
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
