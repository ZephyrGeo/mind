"use strict";

const React = require("react");
const { createRoot } = require("react-dom/client");

const h = React.createElement;
const { useEffect, useRef, useState } = React;
const API_BASE = window.__MIND_API__ ?? "http://127.0.0.1:8000";
const LOCAL_TOKEN = "local-demo-token";

const navigation = [
  { icon: "chat-circle", label: "Chat", active: true },
  { icon: "magnifying-glass", label: "Research" },
  { icon: "diamond", label: "Memory" },
  { icon: "arrow-clockwise", label: "Heartbeats" },
];

const suggestions = [
  {
    title: "Turn a fuzzy goal into next steps",
    prompt: "Help me turn a vague product idea into a concrete one-week plan.",
  },
  {
    title: "Map a topic and its open questions",
    prompt: "Create a research plan for evaluating personal AI agent products.",
  },
  {
    title: "Find the signal in my notes",
    prompt: "Show me how you would extract decisions, risks, and follow-ups from meeting notes.",
  },
];

function Icon({ name, weight = "regular", className = "" }) {
  const weightClass = weight === "fill" ? "ph-fill" : "ph";
  return h("i", {
    className: `${weightClass} ph-${name}${className ? ` ${className}` : ""}`,
    "aria-hidden": "true",
  });
}

function conversationGroupLabel(updatedAt, now = new Date()) {
  const updatedDate = new Date(updatedAt);
  if (Number.isNaN(updatedDate.getTime())) return "Older";

  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const conversationDay = Date.UTC(
    updatedDate.getFullYear(),
    updatedDate.getMonth(),
    updatedDate.getDate(),
  );
  const daysAgo = Math.floor((today - conversationDay) / 86_400_000);

  if (daysAgo <= 0) return "Today";
  if (daysAgo === 1) return "Yesterday";
  if (daysAgo < 7) return "Previous 7 Days";
  if (daysAgo < 30) return "Previous 30 Days";

  return updatedDate.toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

function groupConversations(conversations) {
  const groups = [];
  for (const conversation of conversations) {
    const label = conversationGroupLabel(conversation.updated_at);
    const currentGroup = groups.at(-1);
    if (currentGroup?.label === label) {
      currentGroup.conversations.push(conversation);
    } else {
      groups.push({ label, conversations: [conversation] });
    }
  }
  return groups;
}

function formatConversationTime(updatedAt) {
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  const isToday =
    date.getFullYear() === today.getFullYear() &&
    date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate();
  if (!isToday) return "";
  return date.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

function Brand({ onCollapse }) {
  return h(
    "div",
    { className: "brand" },
    h(
      "span",
      { className: "brand-mark", "aria-hidden": "true" },
      h(Icon, { name: "star-four", weight: "fill" }),
    ),
    h("span", null, "Mind"),
    h(
      "button",
      {
        className: "sidebar-toggle",
        type: "button",
        onClick: onCollapse,
        "aria-label": "Collapse sidebar",
        title: "Collapse sidebar",
      },
      h(Icon, { name: "sidebar-simple" }),
    ),
  );
}

function Sidebar({
  conversations,
  activeConversationId,
  onCollapse,
  onNewChat,
  onOpenConversation,
  onDeleteConversation,
}) {
  const [conversationQuery, setConversationQuery] = useState("");
  const searchRef = useRef(null);
  const normalizedQuery = conversationQuery.trim().toLocaleLowerCase();
  const visibleConversations = normalizedQuery
    ? conversations.filter((conversation) =>
        conversation.title.toLocaleLowerCase().includes(normalizedQuery),
      )
    : conversations;
  const conversationGroups = groupConversations(visibleConversations);

  useEffect(() => {
    function focusConversationSearch(event) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    }
    window.addEventListener("keydown", focusConversationSearch);
    return () => window.removeEventListener("keydown", focusConversationSearch);
  }, []);

  return h(
    "aside",
    { className: "sidebar" },
    h(Brand, { onCollapse }),
    h(
      "button",
      { className: "new-chat-button", type: "button", onClick: onNewChat },
      h(Icon, { name: "plus" }),
      h("span", null, "New conversation"),
    ),
    h(
      "label",
      { className: "conversation-search" },
      h(Icon, { name: "magnifying-glass" }),
      h("input", {
        ref: searchRef,
        type: "search",
        value: conversationQuery,
        onChange: (event) => setConversationQuery(event.target.value),
        placeholder: "Search conversations",
        "aria-label": "Search conversations",
      }),
      h("kbd", null, "⌘K"),
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
          h(Icon, { name: item.icon, className: "nav-symbol" }),
          h("span", null, item.label),
          item.active ? h("span", { className: "nav-indicator" }) : null,
        ),
      ),
    ),
    h(
      "div",
      { className: "conversation-list" },
      visibleConversations.length
        ? conversationGroups.map((group) =>
            h(
              "section",
              { className: "conversation-group", key: group.label },
              h("div", { className: "conversation-group-label" }, group.label),
              group.conversations.map((conversation) => {
                const updatedTime = formatConversationTime(conversation.updated_at);
                return h(
                  "div",
                  { className: "conversation-row", key: conversation.id },
                  h(
                    "button",
                    {
                      className: `conversation-item${
                        conversation.id === activeConversationId ? " active" : ""
                      }`,
                      type: "button",
                      onClick: () => onOpenConversation(conversation),
                    },
                    h(
                      "span",
                      { className: "conversation-title" },
                      conversation.title,
                    ),
                    updatedTime
                      ? h("time", { dateTime: conversation.updated_at }, updatedTime)
                      : null,
                    h(
                      "small",
                      null,
                      `${conversation.message_count} messages`,
                    ),
                  ),
                  h(
                    "button",
                    {
                      className: "conversation-delete",
                      type: "button",
                      "aria-label": `Delete ${conversation.title}`,
                      title: "Delete conversation",
                      onClick: () => onDeleteConversation(conversation),
                    },
                    h(Icon, { name: "trash" }),
                  ),
                );
              }),
            ),
          )
        : h(
            "div",
            { className: "empty-history" },
            normalizedQuery
              ? `No conversations match “${conversationQuery.trim()}”.`
              : "Your conversations will appear here.",
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
      h(
        "button",
        {
          className: "icon-button ghost",
          type: "button",
          "aria-label": "Settings",
        },
        h(Icon, { name: "dots-three" }),
      ),
    ),
  );
}

function Header({
  apiState,
  conversationTitle,
  providerInfo,
  sidebarCollapsed,
  onToggleSidebar,
  onProviderInfo,
}) {
  const providerDetail = providerInfo.billable
    ? "DeepSeek Provider · model calls may incur cost"
    : "Fake Provider · no model calls · no cloud cost";

  return h(
    "header",
    { className: "topbar" },
    h(
      "div",
      { className: "topbar-title-group" },
      h(
        "button",
        {
          className: `mobile-menu${sidebarCollapsed ? " visible" : ""}`,
          type: "button",
          onClick: onToggleSidebar,
          "aria-label": "Open sidebar",
          title: "Open sidebar",
        },
        h(Icon, { name: "sidebar-simple" }),
      ),
      h(
        "button",
        {
          className: "conversation-selector",
          type: "button",
          onClick: onProviderInfo,
          title: providerDetail,
        },
        h(
          "span",
          { className: "conversation-selector-copy" },
          h("strong", null, conversationTitle),
          h(
            "small",
            null,
            providerInfo.billable ? "DeepSeek model" : "Local model",
          ),
        ),
        h(Icon, { name: "caret-down" }),
      ),
    ),
    h(
      "span",
      { className: `api-status ${apiState}` },
      h("span", { className: "status-dot" }),
      apiState === "online"
        ? "Local API ready"
        : apiState === "checking"
          ? "Checking API"
          : "API offline",
    ),
  );
}

function Welcome() {
  return h(
    "div",
    { className: "welcome" },
    h(
      "span",
      { className: "welcome-mark", "aria-hidden": "true" },
      h(Icon, { name: "star-four", weight: "fill" }),
    ),
    h("h2", null, "What should we make sense of?"),
  );
}

function SuggestionList({ onSuggestion }) {
  return h(
    "div",
    { className: "suggestion-list", "aria-label": "Suggested prompts" },
    suggestions.map((suggestion) =>
      h(
        "button",
        {
          className: "suggestion-chip",
          type: "button",
          key: suggestion.title,
          onClick: () => onSuggestion(suggestion.prompt),
        },
        h(Icon, { name: "star-four", weight: "fill" }),
        h("span", null, suggestion.title),
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
      message.role === "assistant"
        ? h(Icon, { name: "star-four", weight: "fill" })
        : "FY",
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

function ModeSwitch({ mode, onModeChange }) {
  return h(
    "div",
    { className: "composer-mode-switch", role: "group", "aria-label": "Agent mode" },
    [
      { value: "chat", label: "Chat", icon: "chat-circle" },
      { value: "research", label: "Research", icon: "magnifying-glass" },
    ].map((option) =>
      h(
        "button",
        {
          key: option.value,
          className: mode === option.value ? "selected" : "",
          type: "button",
          onClick: () => onModeChange(option.value),
        },
        h(Icon, { name: option.icon }),
        option.label,
      ),
    ),
  );
}

function AttachmentList({ attachments }) {
  if (!attachments.length) return null;
  return h(
    "div",
    { className: "attachment-row" },
    attachments.map((file) =>
      h(
        "span",
        { className: "attachment-chip", key: `${file.name}-${file.size}` },
        h(Icon, { name: "file-text" }),
        file.name,
      ),
    ),
  );
}

function Composer({
  value,
  onChange,
  onSend,
  onStop,
  isStreaming,
  mode,
  onModeChange,
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
    h(AttachmentList, { attachments }),
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
          h(ModeSwitch, { mode, onModeChange }),
          h("span", { className: "toolbar-divider", "aria-hidden": "true" }),
          h(
            "label",
            { className: "tool-button", title: "Stage a file for the next phase" },
            h(Icon, { name: "paperclip" }),
            h("input", { type: "file", multiple: true, onChange: onFiles }),
          ),
          h(
            "button",
            {
              className: "tool-button",
              type: "button",
              onClick: onVoice,
              "aria-label": "Voice input",
            },
            h(Icon, { name: "microphone" }),
          ),
        ),
        h(
          "div",
          { className: "composer-actions" },
          h(
            "span",
            { className: "context-meter" },
            h("span", { className: "context-dot", "aria-hidden": "true" }),
            h("span", null, "Local context"),
            h(Icon, { name: "caret-down" }),
          ),
          isStreaming
            ? h(
                "button",
                {
                  className: "send-button stop",
                  type: "button",
                  onClick: onStop,
                  "aria-label": "Stop generating",
                },
                h(Icon, { name: "stop", weight: "fill" }),
              )
            : h(
                "button",
                {
                  className: "send-button",
                  type: "button",
                  onClick: onSend,
                  disabled: !value.trim(),
                  "aria-label": "Send message",
                },
                h(Icon, { name: "arrow-up" }),
              ),
        ),
      ),
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
  const [conversationTitle, setConversationTitle] = useState("New conversation");
  const [isStreaming, setIsStreaming] = useState(false);
  const [attachments, setAttachments] = useState([]);
  const [toast, setToast] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [providerInfo, setProviderInfo] = useState({ name: "fake", billable: false });
  const abortRef = useRef(null);
  const endRef = useRef(null);

  async function loadConversations() {
    try {
      const [healthResponse, response] = await Promise.all([
        fetch(`${API_BASE}/api/health`),
        fetch(`${API_BASE}/api/conversations`, {
          headers: { Authorization: `Bearer ${LOCAL_TOKEN}` },
        }),
      ]);
      if (!healthResponse.ok || !response.ok) throw new Error("API unavailable");
      const [health, payload] = await Promise.all([
        healthResponse.json(),
        response.json(),
      ]);
      setConversations(payload.conversations);
      setProviderInfo({
        name: health.provider,
        billable: health.billable_model_calls,
      });
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
    setConversationTitle("New conversation");
    setMessages([]);
    setInput("");
    setAttachments([]);
    setSidebarOpen(false);
  }

  async function openConversation(conversation) {
    abortRef.current?.abort();
    setIsStreaming(false);
    setApiState("checking");
    try {
      const response = await fetch(
        `${API_BASE}/api/conversations/${conversation.id}`,
        { headers: { Authorization: `Bearer ${LOCAL_TOKEN}` } },
      );
      if (!response.ok) throw new Error("Conversation unavailable");
      const payload = await response.json();
      setConversationId(payload.id);
      setConversationTitle(payload.title);
      setMode(payload.mode);
      setMessages(
        payload.messages.map((message) => ({
          id: message.id,
          role: message.role,
          content: message.content,
        })),
      );
      setInput("");
      setAttachments([]);
      setSidebarOpen(false);
      setApiState("online");
    } catch {
      setApiState("offline");
      setToast("The conversation could not be opened.");
    }
  }

  async function deleteConversation(conversation) {
    const confirmed = window.confirm(
      `Delete “${conversation.title}”? All messages in this conversation will be permanently removed. This cannot be undone.`,
    );
    if (!confirmed) return;

    if (conversation.id === conversationId) {
      abortRef.current?.abort();
      setIsStreaming(false);
    }
    setApiState("checking");
    try {
      const response = await fetch(
        `${API_BASE}/api/conversations/${conversation.id}`,
        {
          method: "DELETE",
          headers: { Authorization: `Bearer ${LOCAL_TOKEN}` },
        },
      );
      if (response.status !== 204) throw new Error("Delete failed");
      setConversations((current) =>
        current.filter((item) => item.id !== conversation.id),
      );
      if (conversation.id === conversationId) resetConversation();
      setApiState("online");
      setToast("Conversation deleted.");
    } catch {
      setApiState("offline");
      setToast("The conversation could not be deleted.");
    }
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
    if (!conversationId) {
      setConversationTitle(text.replace(/\s+/g, " ").slice(0, 56));
    }
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
          attachments: attachments.map((file) => ({
            name: file.name,
            size: file.size,
          })),
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
          if (event.type === "done") setConversationId(event.conversation_id);
          if (event.type === "error") {
            setMessages((current) =>
              current.map((message) =>
                message.id === assistantId
                  ? { ...message, content: event.message }
                  : message,
              ),
            );
            setToast(
              event.retryable
                ? "The model request failed. You can retry."
                : "Check the model provider configuration.",
            );
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
                    "Mind could not complete the request. Check the local API and model provider settings, then try again.",
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
      setToast(
        `${files.length} file${files.length > 1 ? "s" : ""} staged locally. Ingestion arrives in phase 2.`,
      );
    }
  }

  const composerProps = {
    value: input,
    onChange: setInput,
    onSend: sendMessage,
    onStop: stopStreaming,
    isStreaming,
    mode,
    onModeChange: setMode,
    attachments,
    onFiles: stageFiles,
    onVoice: () => setToast("Voice input is planned for phase 2."),
  };

  function selectSuggestion(prompt) {
    setInput(prompt);
    requestAnimationFrame(() => document.querySelector("textarea")?.focus());
  }

  function collapseSidebar() {
    if (window.matchMedia("(max-width: 980px)").matches) {
      setSidebarOpen(false);
      return;
    }
    setSidebarCollapsed(true);
  }

  function openSidebar() {
    if (window.matchMedia("(max-width: 980px)").matches) {
      setSidebarOpen((value) => !value);
      return;
    }
    setSidebarCollapsed(false);
  }

  return h(
    "div",
    {
      className: `app-shell${sidebarCollapsed ? " sidebar-collapsed" : ""}`,
    },
    h("div", {
      className: `sidebar-backdrop${sidebarOpen ? " visible" : ""}`,
      onClick: () => setSidebarOpen(false),
    }),
    h(
      "div",
      { className: `sidebar-container${sidebarOpen ? " open" : ""}` },
      h(Sidebar, {
        conversations,
        activeConversationId: conversationId,
        onCollapse: collapseSidebar,
        onNewChat: resetConversation,
        onOpenConversation: openConversation,
        onDeleteConversation: deleteConversation,
      }),
    ),
    h(
      "main",
      { className: "main-panel" },
      h(Header, {
        apiState,
        conversationTitle,
        providerInfo,
        sidebarCollapsed,
        onToggleSidebar: openSidebar,
        onProviderInfo: () =>
          setToast(
            providerInfo.billable
              ? "DeepSeek is configured through the project-local environment."
              : "The deterministic local provider is active.",
          ),
      }),
      h(
        "div",
        { className: `workspace${messages.length ? " has-messages" : ""}` },
        messages.length
          ? h(
              "div",
              { className: "conversation-workspace" },
              h(Conversation, { messages, endRef }),
              h(Composer, composerProps),
            )
          : h(
              "section",
              { className: "empty-workspace" },
              h(Welcome),
              h(Composer, composerProps),
              h(SuggestionList, { onSuggestion: selectSuggestion }),
            ),
      ),
    ),
    toast ? h("div", { className: "toast", role: "status" }, toast) : null,
  );
}

createRoot(document.getElementById("root")).render(h(App));
