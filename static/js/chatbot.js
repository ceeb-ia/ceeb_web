// === CHATBOT CEEB — Versió neta, estable i amb persistència ===
document.addEventListener("DOMContentLoaded", () => {

  // ELEMENTS DOM
  const widget = document.getElementById("chatbot");
  const openBtn = document.getElementById("chatbot-open");
  const minimizeBtn = document.getElementById("minimize-chatbot");
  const closeBtn = document.getElementById("close-chatbot");

  const messagesBox = document.getElementById("chatbot-messages");
  const input = document.getElementById("user-input");
  const sendBtn = document.getElementById("send-message");
  const loadingSpinner = document.getElementById("loading-spinner");

  if (!widget || !openBtn || !minimizeBtn || !closeBtn || !messagesBox || !input || !sendBtn || !loadingSpinner) {
    return;
  }

  // CLAUS LOCALSTORAGE
  const KEY_VISIBLE = "ceeb_chat_visible";      // true | false
  const KEY_HISTORY = "ceeb_chat_history";      // array missatges
  const KEY_POSITION = "ceeb_chat_position";    // {left, top}

  // POSICIONAMENT ---------------------------------------------------------
  function clampPos(left, top) {
    const maxLeft = window.innerWidth - widget.offsetWidth;
    const maxTop = window.innerHeight - widget.offsetHeight;

    return {
      left: Math.max(0, Math.min(left, maxLeft)),
      top: Math.max(0, Math.min(top, maxTop)),
    };
  }

  function savePosition() {
    const rect = widget.getBoundingClientRect();
    localStorage.setItem(KEY_POSITION, JSON.stringify({
      left: rect.left,
      top: rect.top
    }));
  }

  function restorePosition() {
    const saved = localStorage.getItem(KEY_POSITION);
    if (!saved) return;

    try {
      const pos = JSON.parse(saved);
      const safe = clampPos(pos.left, pos.top);
      widget.style.left = safe.left + "px";
      widget.style.top = safe.top + "px";
      widget.style.right = "auto";
      widget.style.bottom = "auto";
    } catch { }
  }

  // HISTORIAL --------------------------------------------------------------
  function saveHistory(history) {
    localStorage.setItem(KEY_HISTORY, JSON.stringify(history));
  }

  function loadHistory() {
    const raw = localStorage.getItem(KEY_HISTORY);
    if (!raw) return [];
    try {
      return JSON.parse(raw);
    } catch {
      return [];
    }
  }

  function renderHistory(history) {
    messagesBox.innerHTML = "";
    history.forEach(m => {
      addMessage(m.content, m.role === "user" ? "user" : "bot", false);
    });
  }

  // MOSTRAR MISSATGE -------------------------------------------------------
  function addMessage(text, who = "user", save = true) {
    const wrap = document.createElement("div");
    wrap.className = `msg ${who}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    wrap.appendChild(bubble);
    messagesBox.appendChild(wrap);
    messagesBox.scrollTop = messagesBox.scrollHeight;

    // Guardar l’historial si toca
    if (save) {
      history.push({ role: who === "user" ? "user" : "assistant", content: text });
      saveHistory(history);
    }
  }

  // ESTATS DEL XAT ---------------------------------------------------------
  function openChat() {
    widget.classList.remove("minimized");
    widget.classList.remove("hidden");
    openBtn.classList.add("minimized");
    localStorage.setItem(KEY_VISIBLE, "true");

    restorePosition();
  }

  function minimizeChat() {
    widget.classList.add("minimized");
    openBtn.classList.remove("minimized");
    localStorage.setItem(KEY_VISIBLE, "false");
  }

  function closeChat() {
    widget.classList.add("hidden");
    widget.classList.add("minimized");
    openBtn.classList.remove("minimized");

    // RESET TOTAL
    localStorage.removeItem(KEY_VISIBLE);
    localStorage.removeItem(KEY_HISTORY);
    localStorage.removeItem(KEY_POSITION);

    history = [];

    // Reset de contingut i missatge inicial únic
    messagesBox.innerHTML = "";
    addMessage("Hola! Sóc el xat del CEEB. Pregunta’m el que vulguis. ✨", "bot", true);

    // POSICIÓ PER DEFECTE (abaix-dreta)
    widget.style.left = "auto";
    widget.style.top = "auto";
    widget.style.right = "20px";
    widget.style.bottom = "20px";
  }

  // INICIALITZACIÓ ---------------------------------------------------------
  let history = loadHistory();
  const visible = localStorage.getItem(KEY_VISIBLE) === "true";

  if (visible) {
    openChat();
    if (history.length > 0) renderHistory(history);
    else {
      addMessage("Hola! Sóc el xat del CEEB. Pregunta’m el que vulguis. ✨", "bot");
    }
  } else {
    minimizeChat(); // només botó flotant visible
  }

  // BOTONS ----------------------------------------------------------------
  openBtn.addEventListener("click", () => {
    openChat();

    if (history.length === 0) {
      messagesBox.innerHTML = "";
      addMessage("Hola! Sóc el xat del CEEB. Pregunta’m el que vulguis. ✨", "bot");
    } else {
      renderHistory(history);
    }
  });

  minimizeBtn.addEventListener("click", minimizeChat);
  closeBtn.addEventListener("click", closeChat);

  // ENVIAR MISSATGE --------------------------------------------------------
  async function handleSend() {
    const text = input.value.trim();
    if (!text) return;

    addMessage(text, "user");
    input.value = "";

    sendBtn.disabled = true;
    loadingSpinner.classList.remove("hidden");

    try {
      const res = await fetch("/chatbot/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          history: history,
          session_id: Date.now().toString(),
        }),
      });

      const data = await res.json();
      addMessage(data.reply || "Ho sento, hi ha hagut un error.", "bot");

    } catch {
      addMessage("Hi ha hagut un error de connexió.", "bot");
    }

    finally {
      sendBtn.disabled = false;
      loadingSpinner.classList.add("hidden");
    }
  }

  sendBtn.addEventListener("click", handleSend);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  });

  // DRAG & DROP -------------------------------------------------------------
  let drag = false, sx = 0, sy = 0, sl = 0, st = 0;

  document.getElementById("chatbot-header").addEventListener("mousedown", e => {
    if (e.target.closest("#close-chatbot") || e.target.closest("#minimize-chatbot")) return;

    drag = true;
    sx = e.clientX; sy = e.clientY;
    const rect = widget.getBoundingClientRect();
    sl = rect.left; st = rect.top;

    document.body.style.userSelect = "none";
  });

  document.addEventListener("mousemove", e => {
    if (!drag) return;
    const { left, top } = clampPos(sl + (e.clientX - sx), st + (e.clientY - sy));
    widget.style.left = left + "px";
    widget.style.top = top + "px";
    widget.style.right = "auto";
    widget.style.bottom = "auto";
  });

  document.addEventListener("mouseup", () => {
    if (drag) savePosition();
    drag = false;
    document.body.style.userSelect = "";
  });

// ---------- REDIMENSIONAMENT MANUAL ----------
  let isResizing = false;
  let resizeStartX = 0, resizeStartY = 0, startWidth = 0, startHeight = 0;

  // Crea un "handler" per redimensionar a la cantonada inferior dreta
  const resizeHandle = document.createElement('div');
  resizeHandle.style.position = 'absolute';
  resizeHandle.style.width = '15px';
  resizeHandle.style.height = '15px';
  resizeHandle.style.right = '0';
  resizeHandle.style.bottom = '0';
  resizeHandle.style.cursor = 'nwse-resize';
  resizeHandle.style.background = 'rgba(0, 0, 0, 0.2)';
  widget.appendChild(resizeHandle);

  const startResize = (e) => {
    isResizing = true;
    const p = ('touches' in e) ? e.touches[0] : e;
    resizeStartX = p.clientX;
    resizeStartY = p.clientY;
    const rect = widget.getBoundingClientRect();
    startWidth = rect.width;
    startHeight = rect.height;

    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onResize);
    document.addEventListener('mouseup', stopResize);
  };

  const onResize = (e) => {
    if (!isResizing) return;
    const p = ('touches' in e) ? e.touches[0] : e;
    const newWidth = Math.max(200, startWidth + (p.clientX - resizeStartX)); // Amplada mínima: 200px
    const newHeight = Math.max(150, startHeight + (p.clientY - resizeStartY)); // Alçada mínima: 150px
    widget.style.width = `${newWidth}px`;
    widget.style.height = `${newHeight}px`;
  };

  const stopResize = () => {
    if (!isResizing) return;
    isResizing = false;
    document.body.style.userSelect = '';
    document.removeEventListener('mousemove', onResize);
    document.removeEventListener('mouseup', stopResize);
  };

  resizeHandle.addEventListener('mousedown', startResize);
  resizeHandle.addEventListener('touchstart', startResize, { passive: true });

  // ---------- REDIMENSIONAMENT DES DE TOTES LES CANTONADES I LATERALS ----------
  const resizeDirections = [
    { name: 'top', cursor: 'ns-resize', style: { top: '0', left: '0', right: '0', height: '5px' } },
    { name: 'bottom', cursor: 'ns-resize', style: { bottom: '0', left: '0', right: '0', height: '5px' } },
    { name: 'left', cursor: 'ew-resize', style: { top: '0', bottom: '0', left: '0', width: '5px' } },
    { name: 'right', cursor: 'ew-resize', style: { top: '0', bottom: '0', right: '0', width: '5px' } },
    { name: 'top-left', cursor: 'nwse-resize', style: { top: '0', left: '0', width: '10px', height: '10px' } },
    { name: 'top-right', cursor: 'nesw-resize', style: { top: '0', right: '0', width: '10px', height: '10px' } },
    { name: 'bottom-left', cursor: 'nesw-resize', style: { bottom: '0', left: '0', width: '10px', height: '10px' } },
    { name: 'bottom-right', cursor: 'nwse-resize', style: { bottom: '0', right: '0', width: '10px', height: '10px' } },
  ];

  resizeDirections.forEach(({ name, cursor, style }) => {
    const handle = document.createElement('div');
    handle.className = `resize-handle resize-${name}`;
    Object.assign(handle.style, {
      position: 'absolute',
      cursor,
      ...style,
      background: 'rgba(0, 0, 0, 0)',
    });

    widget.appendChild(handle);

    handle.addEventListener('mousedown', (e) => startResizeHandler(e, name));
    handle.addEventListener('touchstart', (e) => startResizeHandler(e, name), { passive: true });
  });

  const startResizeHandler = (e, direction) => {
    isResizing = true;
    const p = ('touches' in e) ? e.touches[0] : e;
    resizeStartX = p.clientX;
    resizeStartY = p.clientY;
    const rect = widget.getBoundingClientRect();
    startWidth = rect.width;
    startHeight = rect.height;
    startLeft = rect.left;
    startTop = rect.top;

    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', (event) => onResizeHandler(event, direction));
    document.addEventListener('mouseup', stopResizeHandler);
  };

  const onResizeHandler = (e, direction) => {
    if (!isResizing) return;
    const p = ('touches' in e) ? e.touches[0] : e;
    let newWidth = startWidth;
    let newHeight = startHeight;
    let newLeft = startLeft;
    let newTop = startTop;

    if (direction.includes('right')) {
      newWidth = Math.max(200, startWidth + (p.clientX - resizeStartX));
    }
    if (direction.includes('left')) {
      newWidth = Math.max(200, startWidth - (p.clientX - resizeStartX));
      newLeft = startLeft + (p.clientX - resizeStartX);
    }
    if (direction.includes('bottom')) {
      newHeight = Math.max(150, startHeight + (p.clientY - resizeStartY));
    }
    if (direction.includes('top')) {
      newHeight = Math.max(150, startHeight - (p.clientY - resizeStartY));
      newTop = startTop + (p.clientY - resizeStartY);
    }

    widget.style.width = `${newWidth}px`;
    widget.style.height = `${newHeight}px`;
    widget.style.left = `${newLeft}px`;
    widget.style.top = `${newTop}px`;
  };

  const stopResizeHandler = () => {
    if (!isResizing) return;
    isResizing = false;
    document.body.style.userSelect = '';
    document.removeEventListener('mousemove', onResizeHandler);
    document.removeEventListener('mouseup', stopResizeHandler);
    savePosFromRect();
  };

});
