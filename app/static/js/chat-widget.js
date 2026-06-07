(function () {
  const widget = document.getElementById("chatWidget");
  const toggle = document.getElementById("chatToggle");
  const closeBtn = document.getElementById("chatClose");
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const messagesEl = document.getElementById("chatMessages");

  if (!widget || !toggle || !closeBtn || !form || !input || !messagesEl) {
    return;
  }

  const VISITOR_STORAGE_KEY = "liveChatVisitorId";
  const renderedIds = new Set();
  const sseSupported = Boolean(window.EventSource);
  let lastMessageId = 0;
  let pollingHandle = null;
  let eventSource = null;
  let reconnectTimer = null;
  let isOpen = false;
  let flickerTimeout = null;
  const prefersReducedMotion =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function generateVisitorId() {
    if (window.crypto && window.crypto.randomUUID) {
      return window.crypto.randomUUID();
    }
    return Math.random().toString(36).slice(2, 12);
  }

  function getVisitorId() {
    let stored = null;
    try {
      stored = window.localStorage.getItem(VISITOR_STORAGE_KEY);
    } catch (error) {
      stored = null;
    }
    if (!stored) {
      stored = generateVisitorId();
      try {
        window.localStorage.setItem(VISITOR_STORAGE_KEY, stored);
      } catch (error) {
        /* ignore storage errors */
      }
    }
    return stored;
  }

  const visitorId = getVisitorId();

  function renderMessage(message) {
    const wrapper = document.createElement("div");
    wrapper.className = `chat-message ${message.sender}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = message.body;
    wrapper.appendChild(bubble);
    messagesEl.appendChild(wrapper);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function addMessage(message) {
    if (!message || renderedIds.has(message.id)) {
      return;
    }
    renderedIds.add(message.id);
    lastMessageId = Math.max(lastMessageId, message.id);
    renderMessage(message);
  }

  function renderHistory(messages) {
    renderedIds.clear();
    messagesEl.innerHTML = "";
    messages
      .slice()
      .sort((a, b) => a.id - b.id)
      .forEach((msg) => addMessage(msg));
  }

  async function pollOnce() {
    try {
      const response = await fetch(
        `/chat/messages?visitor_id=${encodeURIComponent(visitorId)}&after=${lastMessageId}`,
        { cache: "no-store" }
      );
      if (!response.ok) return;
      const data = await response.json();
      if (Array.isArray(data.messages)) {
        data.messages.forEach((msg) => addMessage(msg));
      }
    } catch (error) {
      console.error("Unable to load chat messages", error);
    }
  }

  function startPolling() {
    if (pollingHandle) return;
    pollOnce();
    pollingHandle = setInterval(pollOnce, 3000);
  }

  function stopPolling() {
    if (pollingHandle) {
      clearInterval(pollingHandle);
      pollingHandle = null;
    }
  }

  function handleStreamPayload(payload) {
    if (!payload) return;
    if (payload.type === "ping") {
      return;
    }
    if (payload.type === "history" && Array.isArray(payload.messages)) {
      if (payload.visitor_id && payload.visitor_id !== visitorId) {
        return;
      }
      renderHistory(payload.messages);
    } else if (payload.type === "message" && payload.message) {
      if (!payload.message.visitor_id || payload.message.visitor_id === visitorId) {
        addMessage(payload.message);
      }
    } else if (payload.type === "conversation_deleted") {
      if (!payload.visitor_id || payload.visitor_id === visitorId) {
        renderedIds.clear();
        lastMessageId = 0;
        messagesEl.innerHTML = "";
      }
    }
  }

  function disconnectStream(enableFallback = false) {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (enableFallback) {
      startPolling();
    }
  }

  function connectStream() {
    if (!sseSupported) {
      startPolling();
      return;
    }
    if (eventSource) {
      return;
    }
    eventSource = new EventSource(`/chat/stream?visitor_id=${encodeURIComponent(visitorId)}`);
    eventSource.onopen = () => {
      stopPolling();
    };
    eventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleStreamPayload(payload);
      } catch (error) {
        console.error("Unable to parse chat update", error);
      }
    };
    eventSource.onerror = () => {
      disconnectStream(true);
      reconnectTimer = setTimeout(connectStream, 2000);
    };
  }

  function setOpen(state) {
    isOpen = state;
    widget.classList.toggle("hidden", !state);
    toggle.setAttribute("aria-expanded", state ? "true" : "false");
    if (!window.EventSource) {
      if (state) {
        startPolling();
      } else {
        stopPolling();
      }
    }
    if (state) {
      setTimeout(() => input.focus(), 100);
    }
  }

  function cancelFlicker() {
    if (flickerTimeout) {
      clearTimeout(flickerTimeout);
      flickerTimeout = null;
    }
  }

  function scheduleFlicker() {
    if (prefersReducedMotion) {
      return;
    }
    const minDelay = 6000;
    const maxDelay = 16000;
    const delay = Math.random() * (maxDelay - minDelay) + minDelay;
    flickerTimeout = window.setTimeout(() => {
      toggle.classList.add("is-flickering");
      setTimeout(() => toggle.classList.remove("is-flickering"), 500);
      scheduleFlicker();
    }, delay);
  }

  connectStream();
  scheduleFlicker();
  window.addEventListener("beforeunload", () => {
    cancelFlicker();
    disconnectStream(false);
  });

  toggle.addEventListener("click", () => setOpen(!isOpen));
  closeBtn.addEventListener("click", () => setOpen(false));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = input.value.trim();
    if (!value) return;
    try {
      const response = await fetch("/chat/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sender: "visitor", body: value, visitor_id: visitorId }),
      });
      if (response.ok) {
        const message = await response.json();
        input.value = "";
        addMessage(message);
        pollOnce();
      }
    } catch (error) {
      console.error("Unable to send message", error);
    }
  });

  if (!sseSupported) {
    toggle.addEventListener("click", () => {
      if (!pollingHandle && isOpen) {
        startPolling();
      }
    });
  }
})();
