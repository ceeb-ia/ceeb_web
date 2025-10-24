// === CHATBOT WIDGET (CEEB): visibilitat fiable + posició segura ===
document.addEventListener('DOMContentLoaded', () => {
  const sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  console.log('Session ID generat:', sessionId); // Depuració per assegurar que es genera correctament

  const widget = document.getElementById('chatbot');
  const openBtn = document.getElementById('chatbot-open');
  const minimizeBtn = document.getElementById('minimize-chatbot');
  const closeBtn = document.getElementById('close-chatbot');
  const header = document.getElementById('chatbot-header');
  const messages = document.getElementById('chatbot-messages');
  const input = document.getElementById('user-input');
  const sendBtn = document.getElementById('send-message');

  if (!widget || !openBtn || !minimizeBtn || !closeBtn || !header) {
    console.warn('[Chatbot] Falta algun element (revisa IDs a la vista).');
    return;
  }

  // ---------- ESTAT & HELPERS ----------
  const VISIBLE_KEY = 'chatbot_visible'; // 'true' | 'false'
  const POS_KEY = 'chatbot_pos';         // {left, top}

  function clampPos(left, top) {
    const maxLeft = Math.max(0, window.innerWidth - widget.offsetWidth);
    const maxTop  = Math.max(0, window.innerHeight - widget.offsetHeight);
    return {
      left: Math.max(0, Math.min(left, maxLeft)),
      top:  Math.max(0, Math.min(top, maxTop))
    };
  }

  function applyPos(left, top) {
    widget.style.left = `${left}px`;
    widget.style.top = `${top}px`;
    widget.style.right = 'auto';
    widget.style.bottom = 'auto';
  }

  function restorePos() {
    const saved = localStorage.getItem(POS_KEY);
    if (!saved) return false;
    try {
      const { left, top } = JSON.parse(saved);
      const clamped = clampPos(left ?? 0, top ?? 0);
      applyPos(clamped.left, clamped.top);
      return true;
    } catch {
      return false;
    }
  }

  function savePosFromRect() {
    const rect = widget.getBoundingClientRect();
    localStorage.setItem(POS_KEY, JSON.stringify({ left: rect.left, top: rect.top }));
  }

  function showChat() {
    widget.classList.remove('minimized');    // mostra el xat
    openBtn.classList.add('minimized');      // amaga el botó flotant
    widget.setAttribute('aria-hidden', 'false');
    openBtn.setAttribute('aria-expanded', 'true');
    localStorage.setItem(VISIBLE_KEY, 'true');

    // Si no hi ha posició guardada, col·loca-ho a baix-dreta per defecte
    if (!restorePos()) {
      widget.style.right = '20px';
      widget.style.bottom = '20px';
      widget.style.left = 'auto';
      widget.style.top = 'auto';
    }
    // Si la posició guardada queda fora de pantalla (després d’un resize/navegació), reclampa
    const rect = widget.getBoundingClientRect();
    const clamped = clampPos(rect.left, rect.top);
    applyPos(clamped.left, clamped.top);
  }

  function hideChat() {
    widget.classList.add('minimized');       // amaga el xat
    openBtn.classList.remove('minimized');   // mostra el botó flotant
    widget.setAttribute('aria-hidden', 'true');
    openBtn.setAttribute('aria-expanded', 'false');
    localStorage.setItem(VISIBLE_KEY, 'false');
  }

  // Estat inicial (per defecte: amagat fins que l’usuari obri)
  const wasVisible = localStorage.getItem(VISIBLE_KEY);
  if (wasVisible === 'true') {
    showChat();
  } else {
    hideChat();
  }

  // ---------- BOTONS ----------
  openBtn.addEventListener('click', (e) => { e.preventDefault(); showChat(); });
  minimizeBtn.addEventListener('click', (e) => { e.stopPropagation(); hideChat(); });
  closeBtn.addEventListener('click', (e) => { e.stopPropagation(); hideChat(); });

  // ---------- Enviament (opcional / existent) ----------
  if (sendBtn && input && messages) {
    function addMessage(text, who = 'user') {
      const wrap = document.createElement('div');
      wrap.className = `msg ${who}`;
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      bubble.textContent = text;
      wrap.appendChild(bubble);
      messages.appendChild(wrap);
      messages.scrollTop = messages.scrollHeight;
    }
    async function sendToRag(message, history) {
      console.log('Enviant missatge al backend:', {
        url: '/chatbot/',
        message: message,
        session_id: sessionId,
        history: history
      });
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 600000);
      const res = await fetch('/chatbot/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, history, session_id: sessionId }),
        signal: controller.signal
      });
      try {
        const res = await fetch('/chatbot/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, history, session_id: sessionId }),
          signal: controller.signal
        });
        clearTimeout(timeoutId); // Cancel·la el timeout si la resposta arriba a temps
        if (!res.ok) throw new Error('Error del servidor');
        return await res.json();
      } catch (error) {
        if (error.name === 'AbortError') {
          throw new Error('La petició ha superat el temps d’espera (timeout).');
        }
        throw error;
      }
    }
    const history = [];
    async function handleSend() {
      const text = input.value.trim();
      if (!text) return;

      addMessage(text, 'user');
      history.push({ role: 'user', content: text });
      input.value = '';

      sendBtn.disabled = true; // Desactiva el botó
      const loadingSpinner = document.getElementById('loading-spinner');
      loadingSpinner.classList.remove('hidden'); // Mostra el loader

      try {
        const data = await sendToRag(text, history);
        const reply = (data && data.reply) ? data.reply : 'Ho sento, ara mateix no puc respondre. Torna-ho a provar.';
        addMessage(reply, 'bot');
        history.push({ role: 'assistant', content: reply });
      } catch {
        addMessage('Hi ha hagut un error de connexió. Si us plau, intenta-ho de nou.', 'bot');
      } finally {
        sendBtn.disabled = false; // Reactiva el botó
        loadingSpinner.classList.add('hidden'); // Amaga el loader
      }
    }
    sendBtn.removeEventListener('click', handleSend); // Elimina listeners duplicats
    sendBtn.addEventListener('click', handleSend);

    input.removeEventListener('keydown', handleInputKeydown); // Elimina listeners duplicats
    input.addEventListener('keydown', handleInputKeydown);
    function handleInputKeydown(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    }
  }

  // ---------- DRAG NOMÉS AL HEADER ----------
  let isDragging = false;
  let startX = 0, startY = 0, startLeft = 0, startTop = 0;

  const startDrag = (e) => {
    // No facis drag si el clic és sobre els botons del header
    if (e.target.closest('#close-chatbot') || e.target.closest('#minimize-chatbot')) return;

    isDragging = true;
    const p = ('touches' in e) ? e.touches[0] : e;
    startX = p.clientX;
    startY = p.clientY;

    const rect = widget.getBoundingClientRect();
    startLeft = rect.left;
    startTop = rect.top;

    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onDrag);
    document.addEventListener('mouseup', stopDrag);
  };

  const onDrag = (e) => {
    if (!isDragging) return;
    const p = ('touches' in e) ? e.touches[0] : e;
    const { left, top } = clampPos(startLeft + (p.clientX - startX), startTop + (p.clientY - startY));
    applyPos(left, top);
  };

  const stopDrag = () => {
    if (!isDragging) return;
    isDragging = false;
    document.body.style.userSelect = '';
    document.removeEventListener('mousemove', onDrag);
    document.removeEventListener('mouseup', stopDrag);
    savePosFromRect();
  };

  header.addEventListener('mousedown', startDrag);
  header.addEventListener('touchstart', startDrag, { passive: true });
  header.addEventListener('touchmove', onDrag, { passive: true });
  header.addEventListener('touchend', stopDrag);

  // ---------- SEGURETAT EN RESIZE / NAVEGACIÓ ----------
  window.addEventListener('resize', () => {
    // Si està visible, reclampa la posició a la mida nova de la finestra
    if (localStorage.getItem(VISIBLE_KEY) === 'true') {
      const rect = widget.getBoundingClientRect();
      const clamped = clampPos(rect.left, rect.top);
      applyPos(clamped.left, clamped.top);
      savePosFromRect();
    }
  });
});
