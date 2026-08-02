"use strict";

const React = require("react");
const { createRoot } = require("react-dom/client");

const h = React.createElement;
const { useEffect, useRef, useState } = React;
const API_BASE = window.__MIND_API__ ?? "http://127.0.0.1:8000";
const LOCAL_TOKEN = "local-demo-token";

const navigation = [
  { symbol: "◎", label: "Chat", active: true },
  { symbol: "⌕", label: "Research" },
  { symbol: "◇", label: "Memory" },
  { symbol: "↻", label: "Heartbeats" },
];

const suggestions = [
  {
    eyebrow: "PLAN",
    title: "Turn a fuzzy goal into next steps",
    prompt: "Help me turn a vague product idea into a concrete one-week plan.",
  },
  {
    eyebrow: "RESEARCH",
    title: "Map a topic and its open questions",
    prompt: "Create a research plan for evaluating personal AI agent products.",
  },
  {
    eyebrow: "REFLECT",
    title: "Find the signal in my notes",
    prompt: "Show me how you would extract decisions, risks, and follow-ups from meeting notes.",
  },
];

function Brand() {
  return h(
    "div",
    { className: "brand" },
    h("span", { className: "brand-mark", "aria-hidden": "true" }, "✦"),
    h("span", null, "Mind"),
    h("span", { className: "brand-alpha" }, "LOCAL"),
  );
}

function Sidebar({ conversations, onNewChat }) {
  return h(
    "aside",
    { className: "sidebar" },
    h(Brand),
    h(
      "button",
      { className: "new-chat-button", type: "button", onClick: onNewChat },
      h("span", { "aria-hidden": "true" }, "＋"),
      "New conversation",
    ),
    h(
      "nav",
      { className: "primary-nav", "aria-label": "Primary navigation" },
      navigation.map((item) =>
        h(
          "button",
          {
            className: `nav-item${item.active ? " active" : ""}`,
            type: "button",
            key: item.label,
          },
          h("span", { className: "nav-symbol", "aria-hidden": "true" }, item.symbol),
          item.label,
          item.active ? h("span", { className: "nav-indicator" }) : null,
        ),
      ),
    ),
    h("div", { className: "sidebar-section-label" }, "RECENT"),
    h(
      "div",
      { className: "conversation-list" },
      conversations.length
        ? conversations.slice(0, 5).map((conversation) =>
            h(
              "button",
              { className: "conversation-item", type: "button", key: conversation.id },
              h("span", null, conversation.title),
              h("small", null, `${conversation.message_count} messages`),
            ),
          )
        : h(
            "div",
            { className: "empty-history" },
            "Your conversations will appear here.",
          ),
    ),
    h(
      "div",
      { className: "sidebar-footer" },
      h("div", { className: "avatar" }, "FY"),
      h(
        "div",
        { className: "profile-copy" },
        h("strong", null, "Local developer"),
        h("span", null, "Private workspace"),
      ),
      h("button", { className: "icon-button ghost", type: "button", "aria-label": "Settings" }, "···"),
    ),
  );
}

function Header({ apiState, mode, onModeChange, onToggleSidebar }) {
  return h(
    "header",
    { className: "topbar" },
    h(
      "div",
      { className: "topbar-title-group" },
      h(
        "button",
        {
          className: "mobile-menu",
          type: "button",
          onClick: onToggleSidebar,
          "aria-label": "Open navigation",
        },
        "☰",
      ),
      h("div", null, h("h1", null, "New conversation"), h("p", null, "A calm place to think with your agent")),
    ),
    h(
      "div",
      { className: "topbar-actions" },
      h(
        "div",
        { className: "mode-switch", role: "group", "aria-label": "Agent mode" },
        ["chat", "research"].map((option) =>
          h(
            "button",
            {
              key: option,
              className: mode === option ? "selected" : "",
              type: "button",
              onClick: () => onModeChange(option),
            },
            option === "chat" ? "Chat" : "Research",
          ),
        ),
      ),
      h(
        "span",
        { className: `api-status ${apiState}` },
        h("span", { className: "status-dot" }),
        apiState === "online" ? "Local API ready" : apiState === "checking" ? "Checking API" : "API offline",
      ),
    ),
  );
}

function Welcome({ onSuggestion }) {
  return h(
    "section",
    { className: "welcome" },
    h(
      "div",
      { className: "welcome-mark", "aria-hidden": "true" },
      h("span", null, "✦"),
    ),
    h("p", { className: "overline" }, "YOUR PERSONAL THINKING PARTNER"),
    h("h2", null, "What should we make sense of?"),
    h(
      "p",
      { className: "welcome-copy" },
      "Ask a question, shape a plan, or start a deeper investigation. Mind keeps the process visible and under your control.",
    ),
    h(
      "div",
      { className: "suggestion-grid" },
      suggestions.map((suggestion) =>
        h(
          "button",
          {
            className: "suggestion-card",
            type: "button",
            key: suggestion.eyebrow,
            onClick: () => onSuggestion(suggestion.prompt),
          },
          h("span", null, suggestion.eyebrow),
          h("strong", null, suggestion.title),
          h("i", { "aria-hidden": "true" }, "↗"),
        ),
      ),
    ),
  );
}

function Message({ message }) {
  return h(
    "article",
    { className: `message ${message.role}` },
    h(
      "div",
      { className: "message-avatar", "aria-hidden": "true" },
      message.role === "assistant" ? "✦" : "Y",
    ),
    h(
      "div",
      { className: "message-body" },
      h("div", { className: "message-label" }, message.role === "assistant" ? "MIND" : "YOU"),
      h(
        "div",
        { className: "message-content" },
        message.content || h("span", { className: "typing-dots" }, "Thinking"),
      ),
    ),
  );
}

function Conversation({ messages, endRef }) {
  return h(
    "section",
    { className: "messages", "aria-live": "polite" },
    messages.map((message) => h(Message, { message, key: message.id })),
    h("div", { ref: endRef }),
  );
}

function Composer({
  value,
  onChange,
  onSend,
  onStop,
  isStreaming,
  mode,
  attachments,
  onFiles,
  onVoice,
}) {
  function onKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSend();
    }
  }

  return h(
    "div",
    { className: "composer-wrap" },
    attachments.length
      ? h(
          "div",
          { className: "attachment-row" },
          attachments.map((file) =>
            h("span", { className: "attachment-chip", key: `${file.name}-${file.size}` }, `▤ ${file.name}`),
          ),
        )
      : null,
    h(
      "div",
      { className: "composer" },
      h("textarea", {
        value,
        onChange: (event) => onChange(event.target.value),
        onKeyDown,
        placeholder:
          mode === "research"
            ? "Describe what you want Mind to investigate…"
            : "Message Mind…",
        rows: 1,
        "aria-label": "Message Mind",
      }),
      h(
        "div",
        { className: "composer-toolbar" },
        h(
          "div",
          { className: "composer-tools" },
          h(
            "label",
            { className: "tool-button", title: "Stage a file for the next phase" },
            "＋",
            h("input", { type: "file", multiple: true, onChange: onFiles }),
          ),
          h(
            "button",
            { className: "tool-button", type: "button", onClick: onVoice, "aria-label": "Voice input" },
            "◉",
          ),
          h(
            "span",
            { className: "context-meter" },
            h("span", { "aria-hidden": "true" }, "◌"),
            "Local context",
          ),
        ),
        isStreaming
          ? h("button", { className: "send-button stop", type: "button", onClick: onStop }, "■")
          : h(
              "button",
              {
                className: "send-button",
                type: "button",
                onClick: onSend,
                disabled: !value.trim(),
                "aria-label": "Send message",
              },
              "↑",
            ),
      ),
    ),
    h(
      "div",
      { className: "composer-footnote" },
      h("span", null, "Fake Provider · no model calls · no cloud cost"),
      h("span", null, "Enter to send · Shift+Enter for a new line"),
    ),
  );
}

function App() {
  const [apiState, setApiState] = useState("checking");
  const [mode, setMode] = useState("chat");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [attachments, setAttachments] = useState([]);
  const [toast, setToast] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const abortRef = useRef(null);
  const endRef = useRef(null);

  async function loadConversations() {
    try {
      const response = await fetch(`${API_BASE}/api/conversations`, {
        headers: { Authorization: `Bearer ${LOCAL_TOKEN}` },
      });
      if (!response.ok) throw new Error("API unavailable");
      const payload = await response.json();
      setConversations(payload.conversations);
      setApiState("online");
    } catch {
      setApiState("offline");
    }
  }

  useEffect(() => {
    loadConversations();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(""), 2800);
    return () => clearTimeout(timer);
  }, [toast]);

  function resetConversation() {
    abortRef.current?.abort();
    setConversationId(null);
    setMessages([]);
    setInput("");
    setAttachments([]);
    setSidebarOpen(false);
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || isStreaming) return;

    const userMessage = { id: crypto.randomUUID(), role: "user", content: text };
    const assistantId = crypto.randomUUID();
    setMessages((current) => [
      ...current,
      userMessage,
      { id: assistantId, role: "assistant", content: "" },
    ]);
    setInput("");
    setIsStreaming(true);
    setApiState("checking");

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: {
          Accept: "text/event-stream",
          Authorization: `Bearer ${LOCAL_TOKEN}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          conversation_id: conversationId,
          message: text,
          mode,
          attachments: attachments.map((file) => ({ name: file.name, size: file.size })),
        }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        throw new Error(`API returned ${response.status}`);
      }

      setApiState("online");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
          if (!dataLine) continue;
          const event = JSON.parse(dataLine.slice(6));
          if (event.type === "delta") {
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? { ...message, content: message.content + event.delta }
                  : message,
              ),
            );
          }
          if (event.type === "done") {
            setConversationId(event.conversation_id);
          }
        }
      }

      setAttachments([]);
      await loadConversations();
    } catch (error) {
      if (error.name !== "AbortError") {
        setApiState("offline");
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId
              ? {
                  ...message,
                  content:
                    "I could not reach the local API. Start the workspace and try again; no message was sent to an external model.",
                }
              : message,
          ),
        );
      }
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }

  function stopStreaming() {
    abortRef.current?.abort();
    setIsStreaming(false);
    setToast("Generation stopped.");
  }

  function stageFiles(event) {
    const files = [...event.target.files];
    setAttachments(files);
    if (files.length) {
      setToast(`${files.length} file${files.length > 1 ? "s" : ""} staged locally. Ingestion arrives in phase 2.`);
    }
  }

  return h(
    "div",
    { className: "app-shell" },
    h("div", {
      className: `sidebar-backdrop${sidebarOpen ? " visible" : ""}`,
      onClick: () => setSidebarOpen(false),
    }),
    h(
      "div",
      { className: `sidebar-container${sidebarOpen ? " open" : ""}` },
      h(Sidebar, { conversations, onNewChat: resetConversation }),
    ),
    h(
      "main",
      { className: "main-panel" },
      h(Header, {
        apiState,
        mode,
        onModeChange: setMode,
        onToggleSidebar: () => setSidebarOpen((value) => !value),
      }),
      h(
        "div",
        { className: `workspace${messages.length ? " has-messages" : ""}` },
        messages.length
          ? h(Conversation, { messages, endRef })
          : h(Welcome, {
              onSuggestion: (prompt) => {
                setInput(prompt);
                document.querySelector("textarea")?.focus();
              },
            }),
        h(Composer, {
          value: input,
          onChange: setInput,
          onSend: sendMessage,
          onStop: stopStreaming,
          isStreaming,
          mode,
          attachments,
          onFiles: stageFiles,
          onVoice: () => setToast("Voice input is planned for phase 2."),
        }),
      ),
    ),
    toast ? h("div", { className: "toast", role: "status" }, toast) : null,
  );
}

createRoot(document.getElementById("root")).render(h(App));
