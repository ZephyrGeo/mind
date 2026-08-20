"use strict";

const React = require("react");
const { createRoot } = require("react-dom/client");
const RadixSelect = require("@radix-ui/react-select");
const RadixSwitch = require("@radix-ui/react-switch");
const { createAuthService } = require("./auth.cjs");
const { MarkdownContent } = require("./markdown.cjs");

const h = React.createElement;
const { useEffect, useRef, useState } = React;
const RUNTIME_CONFIG = window.__MIND_CONFIG__ ?? {};
const API_BASE =
  window.__MIND_API__ ?? RUNTIME_CONFIG.apiBase ?? "http://127.0.0.1:8000";
const LOCAL_TOKEN = "local-demo-token";
const authService = createAuthService(RUNTIME_CONFIG, LOCAL_TOKEN);

const researchStatusLabels = {
  queued: "Queued",
  planning: "Planning research",
  collecting: "Searching sources",
  verifying: "Checking evidence",
  synthesizing: "Writing report",
  completed: "Research complete",
  failed: "Research paused after an error",
  cancelled: "Research stopped",
};

const researchStages = [
  { status: "planning", label: "Plan" },
  { status: "collecting", label: "Search" },
  { status: "verifying", label: "Verify" },
  { status: "synthesizing", label: "Write" },
];

const navigation = [
  { icon: "diamond", label: "Memory", view: "memory" },
  { icon: "arrow-clockwise", label: "Heartbeats", view: "heartbeats" },
];

function routeFromLocation() {
  const route = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  if (route === "memory") return { view: "memory", mode: "chat" };
  if (route === "research") return { view: "chat", mode: "research" };
  return { view: "chat", mode: "chat" };
}

function routeHash(view, mode) {
  if (view === "memory") return "#/memory";
  return mode === "research" ? "#/research" : "#/chat";
}

function researchRetrySnapshot(job) {
  const retryTasks = (job.checkpoint?.subtasks ?? []).filter(
    (task) => task.status === "retry_wait",
  );
  const retryTimes = [
    job.provider_backoff_until,
    ...retryTasks.map((task) => task.next_retry_at),
  ]
    .filter(Boolean)
    .map((value) => Date.parse(value))
    .filter(Number.isFinite);
  const nextRetryAt = retryTimes.length ? Math.min(...retryTimes) : null;
  return {
    recoveryState: job.provider_backoff_until
      ? "rate_limited"
      : retryTasks.length
        ? "retrying"
        : null,
    retryAfterSeconds:
      nextRetryAt == null
        ? 0
        : Math.max(0, Math.ceil((nextRetryAt - Date.now()) / 1000)),
  };
}

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
    prompt:
      "Show me how you would extract decisions, risks, and follow-ups from meeting notes.",
  },
];

function Icon({ name, weight = "regular", className = "" }) {
  const weightClass = weight === "fill" ? "ph-fill" : "ph";
  return h("i", {
    className: `${weightClass} ph-${name}${className ? ` ${className}` : ""}`,
    "aria-hidden": "true",
  });
}

async function readSseStream(response, onEvent) {
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => null);
    const error = new Error(
      payload?.error?.message || `Mind API returned ${response.status}.`,
    );
    error.isApiError = true;
    error.code = payload?.error?.code;
    throw error;
  }
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
      const dataLine = frame
        .split("\n")
        .find((line) => line.startsWith("data: "));
      if (dataLine) onEvent(JSON.parse(dataLine.slice(6)));
    }
  }
}

function Brand({ onCollapse }) {
  return h(
    "div",
    { className: "brand" },
    h(
      "span",
      { className: "brand-mark", "aria-hidden": "true" },
      h(Icon, { name: "snowflake" }),
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
  currentUser,
  activeView,
  onCollapse,
  onNewChat,
  onOpenConversation,
  onDeleteConversation,
  onDeleteAccount,
  onSignOut,
  onNavigate,
  memoryReviewCount = 0,
}) {
  const [conversationQuery, setConversationQuery] = useState("");
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [conversationsCollapsed, setConversationsCollapsed] = useState(false);
  const hasProfileActions = Boolean(onSignOut || onDeleteAccount);
  const searchRef = useRef(null);
  const normalizedQuery = conversationQuery.trim().toLocaleLowerCase();
  const visibleConversations = normalizedQuery
    ? conversations.filter((conversation) =>
        conversation.title.toLocaleLowerCase().includes(normalizedQuery),
      )
    : conversations;

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

  useEffect(() => {
    if (!profileMenuOpen) return undefined;
    function closeProfileMenu(event) {
      if (event.key === "Escape") setProfileMenuOpen(false);
      if (
        event.type === "mousedown" &&
        !event.target.closest?.(".sidebar-footer")
      ) {
        setProfileMenuOpen(false);
      }
    }
    window.addEventListener("keydown", closeProfileMenu);
    window.addEventListener("mousedown", closeProfileMenu);
    return () => {
      window.removeEventListener("keydown", closeProfileMenu);
      window.removeEventListener("mousedown", closeProfileMenu);
    };
  }, [profileMenuOpen]);

  function conversationRow(conversation) {
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
        h("span", { className: "conversation-bullet", "aria-hidden": "true" }),
        h("span", { className: "conversation-title" }, conversation.title),
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
  }

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
      navigation.map((item) => {
        const active = item.view === activeView;
        return h(
          "button",
          {
            className: `nav-item${active ? " active" : ""}`,
            type: "button",
            key: item.label,
            onClick: () => onNavigate(item),
          },
          h(Icon, { name: item.icon, className: "nav-symbol" }),
          h("span", null, item.label),
          item.view === "memory" && memoryReviewCount > 0
            ? h(
                "span",
                {
                  className: "nav-badge",
                  "aria-label": `${memoryReviewCount} memories need review`,
                },
                memoryReviewCount > 99 ? "99+" : memoryReviewCount,
              )
            : null,
          active ? h("span", { className: "nav-indicator" }) : null,
        );
      }),
    ),
    h(
      "div",
      { className: "conversation-list" },
      h(
        "section",
        {
          className: `conversation-category${
            conversationsCollapsed ? " collapsed" : ""
          }`,
        },
        h(
          "button",
          {
            className: "conversation-category-label",
            type: "button",
            onClick: () => setConversationsCollapsed((current) => !current),
            "aria-expanded": !conversationsCollapsed,
            "aria-label": `${
              conversationsCollapsed ? "Expand" : "Collapse"
            } chats and researches`,
          },
          h(Icon, { name: "chat-circle" }),
          h("span", null, "Chats and researches"),
          h(Icon, { name: "caret-down", className: "category-caret" }),
        ),
        !conversationsCollapsed
          ? visibleConversations.length
            ? h(
                "div",
                { className: "conversation-category-list" },
                visibleConversations.map(conversationRow),
              )
            : h(
                "p",
                { className: "conversation-category-empty" },
                normalizedQuery
                  ? "No matching conversations."
                  : "No conversations yet.",
              )
          : null,
      ),
    ),
    h(
      "div",
      { className: "sidebar-footer" },
      profileMenuOpen && hasProfileActions
        ? h(
            "div",
            { className: "profile-menu", role: "menu" },
            onSignOut
              ? h(
                  "button",
                  {
                    type: "button",
                    role: "menuitem",
                    onClick: () => {
                      setProfileMenuOpen(false);
                      onSignOut();
                    },
                  },
                  h(Icon, { name: "sign-out" }),
                  "Sign out",
                )
              : null,
            onDeleteAccount
              ? h(
                  "button",
                  {
                    className: "danger",
                    type: "button",
                    role: "menuitem",
                    onClick: () => {
                      setProfileMenuOpen(false);
                      onDeleteAccount();
                    },
                  },
                  h(Icon, { name: "user-minus" }),
                  "Delete account",
                )
              : null,
          )
        : null,
      h(
        hasProfileActions ? "button" : "div",
        {
          className: `sidebar-profile${hasProfileActions ? "" : " static"}`,
          ...(hasProfileActions
            ? {
                type: "button",
                onClick: () => setProfileMenuOpen((open) => !open),
                "aria-expanded": profileMenuOpen,
                "aria-haspopup": "menu",
              }
            : {}),
        },
        h(
          "span",
          { className: "avatar" },
          (currentUser?.displayName || currentUser?.email || "FY")
            .split(/\s+|@/)
            .filter(Boolean)
            .slice(0, 2)
            .map((part) => part[0])
            .join("")
            .toUpperCase(),
        ),
        h(
          "span",
          { className: "profile-copy" },
          h(
            "strong",
            null,
            currentUser?.displayName || currentUser?.email || "Local developer",
          ),
          h(
            "span",
            null,
            currentUser?.email
              ? "Private Firebase workspace"
              : "Private workspace",
          ),
        ),
        hasProfileActions
          ? h(Icon, { name: "dots-three", weight: "bold" })
          : null,
      ),
    ),
  );
}

function Header({ sidebarCollapsed, onToggleSidebar }) {
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
    ),
  );
}

function AppDialog({
  title,
  description,
  confirmLabel = "Confirm",
  danger = false,
  onCancel,
  onConfirm,
  children,
}) {
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    function closeOnEscape(event) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [busy, onCancel]);

  async function confirm() {
    if (busy) return;
    setBusy(true);
    try {
      const shouldClose = await onConfirm();
      if (shouldClose !== false) onCancel();
    } finally {
      setBusy(false);
    }
  }

  return h(
    "div",
    {
      className: "dialog-backdrop",
      onMouseDown: (event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      },
    },
    h(
      "section",
      {
        className: "dialog-card",
        role: "dialog",
        "aria-modal": "true",
        "aria-labelledby": "mind-dialog-title",
      },
      h(
        "div",
        { className: "dialog-heading" },
        h("h2", { id: "mind-dialog-title" }, title),
        description ? h("p", null, description) : null,
      ),
      children ? h("div", { className: "dialog-body" }, children) : null,
      h(
        "div",
        { className: "dialog-actions" },
        h(
          "button",
          {
            className: "secondary",
            type: "button",
            onClick: onCancel,
            disabled: busy,
          },
          "Cancel",
        ),
        h(
          "button",
          {
            className: danger ? "danger" : "primary",
            type: "button",
            onClick: confirm,
            disabled: busy,
          },
          busy ? "Working…" : confirmLabel,
        ),
      ),
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
      h(Icon, { name: "snowflake" }),
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
        h(Icon, { name: "arrow-up-right" }),
        h("span", null, suggestion.title),
      ),
    ),
  );
}

function ResearchProgress({ research, onResume }) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [allSourcesOpen, setAllSourcesOpen] = useState(false);
  if (!research) return null;
  const progress = Math.round((research.progress ?? 0) * 100);
  const canResume = ["failed", "cancelled"].includes(research.status);
  const sources = research.sources ?? [];
  const citations = research.citations ?? [];
  const sourceById = new Map(sources.map((source) => [source.id, source]));
  const citedSourceIds = new Set();
  const citedSourceRows = [];
  for (const citation of citations) {
    if (citedSourceIds.has(citation.source_id)) continue;
    citedSourceIds.add(citation.source_id);
    const source = sourceById.get(citation.source_id);
    citedSourceRows.push(
      citation.kind === "file"
        ? {
            kind: "file",
            source_id: citation.source_id,
            title: citation.title,
            verification_status:
              citation.verification_status ?? "file_provided",
          }
        : {
            kind: "web",
            source_id: citation.source_id,
            title: source?.title ?? citation.title,
            url: source?.url ?? citation.url,
            snippet: source?.snippet ?? "",
          },
    );
  }
  const allSourceRows = Array.from(
    new Map(
      [
        ...sources.map((source) => ({
          kind: "web",
          source_id: source.id,
          title: source.title,
          url: source.url,
          snippet: source.snippet,
        })),
        ...citedSourceRows,
      ].map((source) => [source.source_id, source]),
    ).values(),
  );
  const stageIndex = researchStages.findIndex(
    (stage) => stage.status === research.status,
  );
  const currentStage = research.status === "queued" ? 0 : stageIndex;
  const completedAll = research.status === "completed";
  const keySourceRows = (
    citedSourceRows.length ? citedSourceRows : allSourceRows
  ).slice(0, 6);
  const visibleSourceRows = allSourcesOpen ? allSourceRows : keySourceRows;
  const active = !["completed", "failed", "cancelled"].includes(
    research.status,
  );
  const taskSummary =
    research.totalSubtasks > 0
      ? `${research.completedSubtasks ?? 0}/${research.totalSubtasks} tasks`
      : null;
  const roundSummary =
    research.searchRound > 0
      ? `round ${research.searchRound}/${research.maxSearchRounds ?? 2}`
      : null;
  const toolSummary =
    research.maxTotalToolCalls > 0
      ? `${research.totalToolCalls ?? 0}/${research.maxTotalToolCalls} searches`
      : null;
  const hardMaxTotalToolCalls =
    research.hardMaxTotalToolCalls ??
    (research.maxTotalToolCalls ?? 0) + (research.maxToolCallOverrun ?? 0);
  const hardBudgetReached =
    research.hardBudgetReached ||
    (hardMaxTotalToolCalls > 0 &&
      (research.totalToolCalls ?? 0) >= hardMaxTotalToolCalls);
  const budgetWarning = hardBudgetReached
    ? `Research budget limit reached (${research.totalToolCalls ?? 0}/${hardMaxTotalToolCalls}); search stopped and synthesis is limited to the evidence collected.`
    : research.budgetExceeded
      ? `Used extra search budget (${research.totalToolCalls ?? 0}/${research.maxTotalToolCalls}); no new searches will be started.`
      : null;
  const qualityWarning = research.qualityWarning ?? null;
  const retryAfterSeconds = Math.max(0, research.retryAfterSeconds ?? 0);
  const recoveryNotice =
    research.recoveryState === "rate_limited"
      ? `Too many requests. Research will continue in ${retryAfterSeconds} seconds.`
      : research.recoveryState === "retrying"
        ? `Research is temporarily delayed. Retrying in ${retryAfterSeconds} seconds.`
        : null;
  const degradedNotice =
    research.softDeadlineReached || (research.degradedReasons ?? []).length
      ? "Research is continuing with partial evidence."
      : null;
  const progressNotice =
    recoveryNotice ||
    [budgetWarning, qualityWarning, degradedNotice].filter(Boolean).join(" ") ||
    null;

  function sourceRow(source) {
    if (source.kind === "file") {
      return h(
        "div",
        {
          className: `research-source-row file ${source.verification_status}`,
          key: source.source_id,
          title:
            source.verification_status === "corroborated"
              ? "Claims from this file were corroborated by web evidence."
              : source.verification_status === "conflict"
                ? "At least one claim from this file conflicts with web evidence."
                : "This file is user-provided and is not proof of factual accuracy.",
          role: "listitem",
        },
        h("span", { className: "research-source-id" }, source.source_id),
        h("span", { className: "research-source-title" }, source.title),
        h(
          "span",
          { className: "research-source-status" },
          source.verification_status === "corroborated"
            ? "Verified"
            : source.verification_status === "conflict"
              ? "Conflict"
              : "File",
        ),
      );
    }
    return h(
      "a",
      {
        className: "research-source-row",
        key: source.source_id,
        href: source.url,
        target: "_blank",
        rel: "noreferrer noopener",
        title: source.snippet || source.title,
        role: "listitem",
      },
      h("span", { className: "research-source-id" }, source.source_id),
      h("span", { className: "research-source-title" }, source.title),
      h(Icon, { name: "arrow-square-out" }),
    );
  }

  return h(
    "section",
    { className: "research-progress", "aria-label": "Research progress" },
    h(
      "div",
      { className: "research-progress-heading" },
      h(
        "span",
        { className: `research-state ${research.status ?? "queued"}` },
        h(Icon, {
          name:
            research.status === "completed" ? "check-circle" : "spinner-gap",
        }),
        researchStatusLabels[research.status] ?? "Preparing research",
      ),
      h("span", null, `${progress}%`),
    ),
    h(
      "div",
      {
        className: "research-progress-track",
        role: "progressbar",
        "aria-valuemin": 0,
        "aria-valuemax": 100,
        "aria-valuenow": progress,
      },
      h("span", { style: { width: `${progress}%` } }),
    ),
    h(
      "ol",
      { className: "research-stage-list", "aria-label": "Research stages" },
      researchStages.map((stage, index) =>
        h(
          "li",
          {
            key: stage.status,
            className: `${
              completedAll || index < currentStage
                ? "completed"
                : index === currentStage
                  ? "active"
                  : "pending"
            }`,
          },
          h("span", null, index + 1),
          stage.label,
        ),
      ),
    ),
    h(
      "div",
      { className: "research-progress-meta" },
      h(
        "span",
        null,
        [roundSummary, taskSummary, toolSummary].filter(Boolean).join(" · ") ||
          "Preparing the Research Brief",
      ),
      progressNotice
        ? h(
            "span",
            {
              className: recoveryNotice
                ? "research-recovery-notice"
                : "research-budget-warning",
            },
            progressNotice,
          )
        : active
          ? h("span", null, "This can take several minutes.")
          : null,
    ),
    allSourceRows.length
      ? h(
          "section",
          { className: "research-sources" },
          h(
            "button",
            {
              className: "research-sources-toggle",
              type: "button",
              onClick: () => {
                if (sourcesOpen) setAllSourcesOpen(false);
                setSourcesOpen((current) => !current);
              },
              "aria-expanded": sourcesOpen,
            },
            h(Icon, { name: "books" }),
            h("span", { className: "research-sources-label" }, "Sources"),
            h(
              "span",
              { className: "research-sources-count" },
              allSourceRows.length,
            ),
            h(Icon, {
              name: "caret-down",
              className: `research-sources-caret${sourcesOpen ? " open" : ""}`,
            }),
          ),
          sourcesOpen
            ? h(
                "div",
                { className: "research-sources-panel" },
                completedAll
                  ? [
                      h(
                        "div",
                        { className: "research-sources-toolbar" },
                        h(
                          "span",
                          null,
                          citedSourceRows.length
                            ? "Cited in report"
                            : "Selected sources",
                        ),
                        allSourceRows.length > keySourceRows.length
                          ? h(
                              "button",
                              {
                                className: "research-sources-view-all",
                                type: "button",
                                onClick: () =>
                                  setAllSourcesOpen((current) => !current),
                              },
                              allSourcesOpen
                                ? "Show key sources"
                                : `View all ${allSourceRows.length} sources`,
                            )
                          : null,
                      ),
                      h(
                        "div",
                        { className: "research-source-list", role: "list" },
                        visibleSourceRows.map(sourceRow),
                      ),
                    ]
                  : h(
                      "p",
                      { className: "research-sources-note" },
                      active
                        ? `${allSourceRows.length} sources collected. Key sources will appear with the report.`
                        : `${allSourceRows.length} sources collected.`,
                    ),
              )
            : null,
        )
      : null,
    canResume
      ? h(
          "button",
          {
            className: "research-resume",
            type: "button",
            onClick: () => onResume(research.jobId),
          },
          h(Icon, { name: "arrow-clockwise" }),
          research.status === "cancelled"
            ? "Restart as a new research task"
            : "Resume research",
        )
      : null,
  );
}

function Message({ message, onResumeResearch }) {
  return h(
    "article",
    { className: `message ${message.role}` },
    h(
      "div",
      { className: "message-avatar", "aria-hidden": "true" },
      message.role === "assistant" ? h(Icon, { name: "snowflake" }) : "FY",
    ),
    h(
      "div",
      { className: "message-body" },
      h(
        "div",
        { className: "message-content" },
        message.content
          ? message.role === "assistant"
            ? h(MarkdownContent, {
                content: message.content,
                citations: message.research?.citations,
              })
            : message.content
          : message.research
            ? null
            : h("span", { className: "typing-dots" }, "Thinking"),
      ),
      h(ResearchProgress, {
        research: message.research,
        onResume: (jobId) => onResumeResearch(message.id, jobId),
      }),
    ),
  );
}

function Conversation({ messages, endRef, onResumeResearch }) {
  return h(
    "section",
    { className: "messages", "aria-live": "polite" },
    messages.map((message) =>
      h(Message, { message, key: message.id, onResumeResearch }),
    ),
    h("div", { ref: endRef }),
  );
}

function ModeSwitch({ mode, onModeChange }) {
  return h(
    "div",
    {
      className: "composer-mode-switch",
      role: "group",
      "aria-label": "Agent mode",
    },
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

function AttachmentList({ attachments, onRemove }) {
  if (!attachments.length) return null;
  return h(
    "div",
    { className: "attachment-row" },
    attachments.map((file) =>
      h(
        "span",
        {
          className: `attachment-chip ${file.status ?? "ready"}`,
          key: file.id ?? file.localId,
        },
        h(Icon, { name: "file-text" }),
        h("span", null, file.name),
        file.status === "uploading"
          ? h("span", { className: "attachment-status" }, "Uploading…")
          : h(
              "button",
              {
                type: "button",
                onClick: () => onRemove(file),
                "aria-label": `Remove ${file.name}`,
              },
              h(Icon, { name: "x" }),
            ),
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
  onRemoveFile,
  isUploading,
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
    h(AttachmentList, { attachments, onRemove: onRemoveFile }),
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
            {
              className: "tool-button",
              title: "Attach a TXT or PDF file",
            },
            h(Icon, { name: "paperclip" }),
            h("input", {
              type: "file",
              accept: ".txt,.pdf,text/plain,application/pdf",
              multiple: true,
              disabled: isStreaming || isUploading,
              onChange: onFiles,
            }),
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
                  disabled: !value.trim() || isUploading,
                  "aria-label": "Send message",
                },
                h(Icon, { name: "arrow-up" }),
              ),
        ),
      ),
    ),
  );
}

function friendlyAuthError(error) {
  const code = error?.code ?? "";
  if (code.includes("invalid-credential"))
    return "Email or password is incorrect.";
  if (code.includes("email-already-in-use"))
    return "An account already uses this email.";
  if (code.includes("weak-password"))
    return "Use a password with at least six characters.";
  if (code.includes("invalid-email")) return "Enter a valid email address.";
  if (code.includes("too-many-requests"))
    return "Too many attempts. Please wait and retry.";
  return "Authentication could not be completed. Please try again.";
}

function AuthScreen({ service }) {
  const [view, setView] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState(null);

  async function submit(event) {
    event.preventDefault();
    if (!email.trim() || (view !== "reset" && !password)) return;
    setBusy(true);
    setFeedback(null);
    try {
      if (view === "register") {
        await service.register(email.trim(), password);
      } else if (view === "reset") {
        await service.resetPassword(email.trim());
        setFeedback({ kind: "success", message: "Password reset email sent." });
      } else {
        await service.login(email.trim(), password);
      }
    } catch (error) {
      setFeedback({ kind: "error", message: friendlyAuthError(error) });
    } finally {
      setBusy(false);
    }
  }

  return h(
    "main",
    { className: "auth-page" },
    h(
      "section",
      { className: "auth-card", "aria-labelledby": "auth-title" },
      h(
        "div",
        { className: "auth-brand" },
        h(
          "span",
          { className: "brand-mark", "aria-hidden": "true" },
          h(Icon, { name: "snowflake" }),
        ),
        h("span", null, "Mind"),
      ),
      h(
        "div",
        { className: "auth-heading" },
        h(
          "h1",
          { id: "auth-title" },
          view === "register"
            ? "Create your workspace"
            : view === "reset"
              ? "Reset your password"
              : "Welcome back",
        ),
        h(
          "p",
          null,
          view === "register"
            ? "A private place for conversations and research."
            : view === "reset"
              ? "We will send recovery instructions to your email."
              : "Sign in to continue to your private Mind workspace.",
        ),
      ),
      h(
        "form",
        { className: "auth-form", onSubmit: submit },
        h(
          "label",
          null,
          h("span", null, "Email"),
          h("input", {
            type: "email",
            autoComplete: "email",
            value: email,
            onChange: (event) => setEmail(event.target.value),
            required: true,
          }),
        ),
        view === "reset"
          ? null
          : h(
              "label",
              null,
              h("span", null, "Password"),
              h("input", {
                type: "password",
                autoComplete:
                  view === "register" ? "new-password" : "current-password",
                value: password,
                onChange: (event) => setPassword(event.target.value),
                minLength: 6,
                required: true,
              }),
            ),
        feedback
          ? h(
              "p",
              { className: `auth-feedback ${feedback.kind}`, role: "status" },
              feedback.message,
            )
          : null,
        h(
          "button",
          { className: "auth-submit", type: "submit", disabled: busy },
          busy
            ? "Please wait…"
            : view === "register"
              ? "Create account"
              : view === "reset"
                ? "Send reset email"
                : "Sign in",
        ),
      ),
      h(
        "div",
        { className: "auth-links" },
        view !== "login"
          ? h(
              "button",
              { type: "button", onClick: () => setView("login") },
              "Back to sign in",
            )
          : h(
              "button",
              { type: "button", onClick: () => setView("reset") },
              "Forgot password?",
            ),
        view === "login"
          ? h(
              "button",
              { type: "button", onClick: () => setView("register") },
              "Create account",
            )
          : null,
      ),
    ),
  );
}

function VerifyEmailScreen({ service, user }) {
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(action, successMessage) {
    setBusy(true);
    setFeedback("");
    try {
      await action();
      setFeedback(successMessage);
    } catch (error) {
      setFeedback(friendlyAuthError(error));
    } finally {
      setBusy(false);
    }
  }

  return h(
    "main",
    { className: "auth-page" },
    h(
      "section",
      { className: "auth-card verification-card" },
      h(
        "span",
        { className: "verification-icon" },
        h(Icon, { name: "envelope" }),
      ),
      h("h1", null, "Verify your email"),
      h("p", null, `We sent a verification link to ${user.email}.`),
      feedback
        ? h("p", { className: "auth-feedback success" }, feedback)
        : null,
      h(
        "button",
        {
          className: "auth-submit",
          type: "button",
          disabled: busy,
          onClick: () =>
            run(() => service.refreshUser(), "Verification status refreshed."),
        },
        "I have verified my email",
      ),
      h(
        "div",
        { className: "auth-links" },
        h(
          "button",
          {
            type: "button",
            disabled: busy,
            onClick: () =>
              run(
                () => service.resendVerification(),
                "Verification email sent again.",
              ),
          },
          "Resend email",
        ),
        h(
          "button",
          { type: "button", onClick: () => service.logout() },
          "Sign out",
        ),
      ),
    ),
  );
}

function memorySourceLabel(memory) {
  const kind = memory.provenance?.source_kind;
  const sourceId =
    kind === "research_report"
      ? memory.provenance?.research_job_id
      : memory.provenance?.conversation_id;
  const reference = sourceId ? ` · ${String(sourceId).slice(0, 8)}` : "";
  if (kind === "conversation") return `Conversation${reference}`;
  if (kind === "research_report") return `Research report${reference}`;
  return "Added by you";
}

function memorySourceTitle(memory) {
  const provenance = memory.provenance;
  if (!provenance || provenance.source_kind === "manual") {
    return "This memory was added manually.";
  }
  const parts = [`Source: ${provenance.source_kind}`];
  if (provenance.conversation_id)
    parts.push(`Conversation: ${provenance.conversation_id}`);
  if (provenance.research_job_id)
    parts.push(`Research job: ${provenance.research_job_id}`);
  if (provenance.source_message_id)
    parts.push(`Message: ${provenance.source_message_id}`);
  return parts.join("\n");
}

function memoryReviewLabel(memory) {
  if (memory.status === "conflict") return "Conflict";
  if (memory.status === "stale") return "Needs revalidation";
  if (memory.review_reason === "update") return "Update suggested";
  if (memory.review_reason === "research") return "From Research";
  return "Needs review";
}

function memoryConfirmLabel(memory) {
  if (memory.status === "conflict") return "Use this version";
  if (memory.status === "stale") return "Reconfirm";
  if (memory.review_reason === "update") return "Apply update";
  return "Confirm memory";
}

function memoryTypeLabel(type) {
  return type ? `${type.charAt(0).toUpperCase()}${type.slice(1)}` : "Memory";
}

const memoryTypes = ["goal", "preference", "project", "fact", "decision"];

function MemoryTypeSelect({ value, onValueChange }) {
  return h(
    RadixSelect.Root,
    { value, onValueChange },
    h(
      RadixSelect.Trigger,
      { className: "memory-type-select", "aria-label": "Memory type" },
      h(RadixSelect.Value),
      h(
        RadixSelect.Icon,
        { asChild: true },
        h(Icon, { name: "caret-down" }),
      ),
    ),
    h(
      RadixSelect.Portal,
      null,
      h(
        RadixSelect.Content,
        {
          className: "memory-type-content",
          position: "popper",
          sideOffset: 6,
          align: "start",
        },
        h(
          RadixSelect.Viewport,
          { className: "memory-type-viewport" },
          memoryTypes.map((memoryType) =>
            h(
              RadixSelect.Item,
              {
                className: "memory-type-item",
                key: memoryType,
                value: memoryType,
              },
              h(
                RadixSelect.ItemIndicator,
                { className: "memory-type-indicator" },
                h(Icon, { name: "check" }),
              ),
              h(RadixSelect.ItemText, null, memoryTypeLabel(memoryType)),
            ),
          ),
        ),
      ),
    ),
  );
}

function memoryUpdatedLabel(memory) {
  if (!memory.updated_at) return "";
  const date = new Date(memory.updated_at);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year:
      date.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  }).format(date);
}

function memoryMatchesSearch(memory, query) {
  if (!query) return true;
  return [
    memory.type,
    memory.content,
    ...(Array.isArray(memory.facets) ? memory.facets : []),
    memorySourceLabel(memory),
  ]
    .join(" ")
    .toLocaleLowerCase()
    .includes(query);
}

function MemoryLedger({
  memories,
  loading,
  focusId,
  onRefresh,
  onCreate,
  onConfirm,
  onUpdate,
  onDelete,
}) {
  const [draft, setDraft] = useState("");
  const [type, setType] = useState("fact");
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState(focusId ?? null);
  const [editor, setEditor] = useState(null);
  const query = search.trim().toLocaleLowerCase();
  const visibleMemories = memories.filter((memory) =>
    memoryMatchesSearch(memory, query),
  );
  const reviewItems = visibleMemories.filter((memory) =>
    ["candidate", "conflict", "stale"].includes(memory.status),
  );
  const confirmed = visibleMemories.filter(
    (memory) => memory.status === "active",
  );
  const superseded = visibleMemories.filter(
    (memory) => memory.status === "superseded",
  );
  const memoriesById = new Map(memories.map((memory) => [memory.id, memory]));

  useEffect(() => {
    if (focusId) setExpandedId(focusId);
  }, [focusId]);

  useEffect(() => {
    if (!expandedId && reviewItems.length) setExpandedId(reviewItems[0].id);
  }, [expandedId, reviewItems.length]);

  async function submitMemory(event) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || saving) return;
    setSaving(true);
    const created = await onCreate({ type, content });
    if (created) setDraft("");
    setSaving(false);
  }

  function editMemory(memory) {
    setEditor({ kind: "content", memory, value: memory.content, error: "" });
  }

  function setExpiry(memory) {
    const current = memory.expires_at ? memory.expires_at.slice(0, 10) : "";
    setEditor({ kind: "expiry", memory, value: current, error: "" });
  }

  async function saveEditor() {
    if (!editor) return false;
    const value = editor.value.trim();
    if (editor.kind === "content") {
      if (!value) {
        setEditor((current) => ({
          ...current,
          error: "Memory text cannot be empty.",
        }));
        return false;
      }
      if (value !== editor.memory.content) {
        await onUpdate(editor.memory.id, { content: value });
      }
      return true;
    }

    if (!value) {
      await onUpdate(editor.memory.id, { expires_at: null });
      return true;
    }
    const expiresAt = new Date(`${value}T23:59:59.999Z`);
    if (Number.isNaN(expiresAt.getTime())) {
      setEditor((current) => ({ ...current, error: "Choose a valid date." }));
      return false;
    }
    await onUpdate(editor.memory.id, { expires_at: expiresAt.toISOString() });
    return true;
  }

  function memoryRow(memory) {
    const expired =
      memory.expires_at && new Date(memory.expires_at).getTime() <= Date.now();
    const needsReview = ["candidate", "conflict", "stale"].includes(
      memory.status,
    );
    const previous = memory.supersedes_id
      ? memoriesById.get(memory.supersedes_id)
      : null;
    const expanded = expandedId === memory.id;
    const facets = Array.isArray(memory.facets) ? memory.facets : [];
    const preview = facets.find(
      (facet) =>
        facet.toLocaleLowerCase() !== memory.content.toLocaleLowerCase(),
    );
    const updatedLabel = memoryUpdatedLabel(memory);
    return h(
      "article",
      {
        className: `memory-row status-${memory.status}${needsReview ? " review" : ""}${
          !memory.enabled || expired ? " muted" : ""
        }${expanded ? " expanded" : ""}${focusId === memory.id ? " focused" : ""}`,
        id: `memory-${memory.id}`,
        key: memory.id,
        tabIndex: focusId === memory.id ? -1 : null,
      },
      h(
        "div",
        { className: "memory-row-summary" },
        h(
          "button",
          {
            type: "button",
            className: "memory-row-toggle",
            onClick: () => setExpandedId(expanded ? null : memory.id),
            "aria-expanded": expanded,
          },
          h(
            "span",
            {
              className: `memory-status-icon${needsReview ? " attention" : ""}`,
              "aria-hidden": "true",
            },
            h(Icon, {
              name: needsReview
                ? memory.status === "conflict"
                  ? "warning-circle"
                  : "info"
                : memory.pinned
                  ? "push-pin"
                  : "check-circle",
              weight: memory.pinned ? "fill" : "regular",
            }),
          ),
          h(
            "span",
            { className: `memory-type type-${memory.type}` },
            memoryTypeLabel(memory.type),
          ),
          h(
            "span",
            { className: "memory-row-copy" },
            h("strong", null, memory.content),
            preview ? h("span", null, preview) : null,
          ),
        ),
        needsReview
          ? h(
              "div",
              { className: "memory-row-state-control" },
              h(
                "span",
                { className: `memory-state status-${memory.status}` },
                memoryReviewLabel(memory),
              ),
            )
          : memory.status === "superseded"
            ? h(
                "div",
                { className: "memory-row-state-control" },
                h(
                  "span",
                  { className: "memory-state status-superseded" },
                  "History",
                ),
              )
            : h(
                "div",
                { className: "memory-row-state-control has-switch" },
                h(
                  RadixSwitch.Root,
                  {
                    className: "memory-switch",
                    checked: memory.enabled,
                    onCheckedChange: (checked) =>
                      onUpdate(memory.id, { enabled: checked }),
                    "aria-label": `${memory.enabled ? "Disable" : "Enable"} ${memory.content}`,
                  },
                  h(RadixSwitch.Thumb, { className: "memory-switch-thumb" }),
                ),
                h(
                  "span",
                  { className: "memory-enabled-label" },
                  memory.enabled ? "Enabled" : "Off",
                ),
              ),
        h(
          "span",
          {
            className: "memory-row-source",
            title: memorySourceTitle(memory),
          },
          h("span", null, memorySourceLabel(memory)),
          h("span", null, updatedLabel ? `Updated ${updatedLabel}` : ""),
        ),
      ),
      expanded
        ? h(
            "div",
            { className: "memory-row-detail" },
            h(
              "dl",
              { className: "memory-detail-meta" },
              h(
                "div",
                null,
                h("dt", null, "Confidence"),
                h("dd", null, `${Math.round((memory.confidence ?? 1) * 100)}%`),
              ),
              h(
                "div",
                null,
                h("dt", null, "Expires"),
                h(
                  "dd",
                  null,
                  memory.expires_at
                    ? expired
                      ? "Expired"
                      : memory.expires_at.slice(0, 10)
                    : "No expiry",
                ),
              ),
              h(
                "div",
                null,
                h("dt", null, "Revision"),
                h("dd", null, memory.revision ?? 1),
              ),
              h(
                "div",
                null,
                h("dt", null, "Source"),
                h(
                  "dd",
                  { title: memorySourceTitle(memory) },
                  memorySourceLabel(memory),
                ),
              ),
            ),
            facets.length
              ? h(
                  "div",
                  { className: "memory-facets" },
                  h("span", null, "Included details"),
                  h(
                    "ul",
                    null,
                    facets.map((facet, index) =>
                      h("li", { key: `${memory.id}-facet-${index}` }, facet),
                    ),
                  ),
                )
              : null,
            previous
              ? h(
                  "div",
                  { className: "memory-previous" },
                  h(
                    "span",
                    null,
                    memory.status === "conflict"
                      ? "Conflicts with"
                      : "Previous version",
                  ),
                  h("p", null, previous.content),
                )
              : null,
            h(
              "div",
              { className: "memory-actions" },
              needsReview
                ? h(
                    "button",
                    {
                      type: "button",
                      className: "primary",
                      onClick: () => onConfirm(memory.id),
                    },
                    h(Icon, { name: "check" }),
                    memoryConfirmLabel(memory),
                  )
                : null,
              memory.status !== "superseded"
                ? h(
                    "button",
                    {
                      type: "button",
                      onClick: () =>
                        onUpdate(memory.id, { pinned: !memory.pinned }),
                    },
                    h(Icon, { name: "push-pin" }),
                    memory.pinned ? "Unpin" : "Pin",
                  )
                : null,
              memory.status !== "superseded"
                ? h(
                    "button",
                    { type: "button", onClick: () => editMemory(memory) },
                    h(Icon, { name: "pencil-simple" }),
                    "Edit",
                  )
                : null,
              memory.status !== "superseded"
                ? h(
                    "button",
                    { type: "button", onClick: () => setExpiry(memory) },
                    h(Icon, { name: "calendar-blank" }),
                    "Expiry",
                  )
                : null,
              h(
                "button",
                {
                  type: "button",
                  className: "danger",
                  onClick: () => onDelete(memory),
                },
                h(Icon, { name: "trash" }),
                "Delete",
              ),
            ),
          )
        : null,
    );
  }

  return h(
    "section",
    { className: "memory-ledger" },
    h(
      "div",
      { className: "memory-toolbar" },
      h(
        "div",
        { className: "memory-title" },
        h("h1", null, "Memory"),
        h(
          "p",
          null,
          "Manage what Mind remembers and uses in future conversations.",
        ),
      ),
      h(
        "div",
        { className: "memory-toolbar-actions" },
        h(
          "label",
          { className: "memory-search" },
          h(Icon, { name: "magnifying-glass" }),
          h("input", {
            type: "search",
            value: search,
            onChange: (event) => setSearch(event.target.value),
            placeholder: "Search memories",
            "aria-label": "Search memories",
          }),
        ),
        h(
          "button",
          {
            className: "memory-refresh",
            type: "button",
            onClick: onRefresh,
            disabled: loading,
            "aria-label": loading ? "Refreshing memories" : "Refresh memories",
            title: loading ? "Refreshing…" : "Refresh",
          },
          h(Icon, { name: "arrow-clockwise" }),
        ),
      ),
    ),
    h(
      "form",
      { className: "memory-create", onSubmit: submitMemory },
      h(Icon, { name: "plus", className: "memory-create-icon" }),
      h(MemoryTypeSelect, {
        value: type,
        onValueChange: setType,
      }),
      h("input", {
        value: draft,
        onChange: (event) => setDraft(event.target.value),
        placeholder: "Add something useful for future conversations…",
        maxLength: 1000,
        "aria-label": "New memory",
      }),
      h(
        "button",
        {
          className: "memory-create-submit",
          type: "submit",
          disabled: saving || !draft.trim(),
        },
        saving ? "Saving…" : "Add",
      ),
      h("small", null, "Sensitive credentials are rejected and never saved."),
    ),
    reviewItems.length
      ? h(
          "section",
          { className: "memory-section" },
          h(
            "div",
            { className: "memory-section-heading attention" },
            h("h2", null, "Needs attention"),
            h("span", null, reviewItems.length),
          ),
          h("div", { className: "memory-list" }, reviewItems.map(memoryRow)),
        )
      : null,
    h(
      "section",
      { className: "memory-section" },
      h(
        "div",
        { className: "memory-section-heading" },
        h("h2", null, "Saved"),
        h("span", null, confirmed.length),
      ),
      confirmed.length
        ? h("div", { className: "memory-list" }, confirmed.map(memoryRow))
        : !query
          ? h(
              "div",
              { className: "memory-empty" },
              h(Icon, { name: "diamond" }),
              h(
                "p",
                null,
                loading
                  ? "Loading your Memory Ledger…"
                  : "No confirmed memories yet.",
              ),
            )
          : null,
    ),
    !reviewItems.length && !confirmed.length && query
      ? h(
          "div",
          { className: "memory-empty memory-search-empty" },
          h(Icon, { name: "magnifying-glass" }),
          h("p", null, `No memories match “${search.trim()}”.`),
        )
      : null,
    superseded.length
      ? h(
          "details",
          { className: "memory-history" },
          h(
            "summary",
            null,
            h("span", null, "History"),
            h("small", null, `${superseded.length} replaced memories`),
            h(Icon, { name: "caret-down" }),
          ),
          h("div", { className: "memory-list" }, superseded.map(memoryRow)),
        )
      : null,
    editor
      ? h(
          AppDialog,
          {
            title: editor.kind === "content" ? "Edit memory" : "Set an expiry",
            description:
              editor.kind === "content"
                ? "Update the information Mind may use in future conversations."
                : "Leave the date empty to keep this memory indefinitely.",
            confirmLabel: "Save",
            onCancel: () => setEditor(null),
            onConfirm: saveEditor,
          },
          editor.kind === "content"
            ? h("textarea", {
                className: "dialog-field dialog-textarea",
                value: editor.value,
                onChange: (event) =>
                  setEditor((current) => ({
                    ...current,
                    value: event.target.value,
                    error: "",
                  })),
                maxLength: 1000,
                autoFocus: true,
                "aria-label": "Memory text",
              })
            : h("input", {
                className: "dialog-field",
                type: "date",
                value: editor.value,
                onChange: (event) =>
                  setEditor((current) => ({
                    ...current,
                    value: event.target.value,
                    error: "",
                  })),
                autoFocus: true,
                "aria-label": "Memory expiry date",
              }),
          editor.error
            ? h("p", { className: "dialog-error" }, editor.error)
            : null,
        )
      : null,
  );
}

function MemoryReviewNotice({ notice, onReview, onDismiss }) {
  const primary = notice.candidates[0] ?? null;
  const isConflict = primary?.status === "conflict";
  const isUpdate = primary?.review_reason === "update";
  const title = isConflict
    ? "Memory conflict needs review"
    : isUpdate
      ? "Memory update needs review"
      : notice.count === 1
        ? "New memory needs review"
        : `${notice.count} memories need review`;
  const detail = isConflict
    ? "Choose which version Mind should use in future conversations."
    : isUpdate
      ? "Review the suggested change before Mind replaces the previous version."
      : "Review the suggestion before Mind uses it in future conversations.";

  return h(
    "section",
    {
      className: `memory-review-notice${isConflict ? " conflict" : ""}`,
      role: "status",
      "aria-live": "polite",
    },
    h(
      "span",
      { className: "memory-review-notice-icon", "aria-hidden": "true" },
      h(Icon, { name: isConflict ? "warning" : "brain" }),
    ),
    h(
      "div",
      { className: "memory-review-notice-copy" },
      h("strong", null, title),
      h("p", null, detail),
    ),
    h(
      "div",
      { className: "memory-review-notice-actions" },
      h(
        "button",
        { className: "primary", type: "button", onClick: onReview },
        notice.count === 1 ? "Review memory" : `Review ${notice.count}`,
      ),
      h(
        "button",
        {
          className: "dismiss",
          type: "button",
          onClick: onDismiss,
          "aria-label": "Review memory later",
          title: "Review later",
        },
        h(Icon, { name: "x" }),
      ),
    ),
  );
}

function App({ authSession }) {
  const initialRoute = routeFromLocation();
  const [activeView, setActiveView] = useState(initialRoute.view);
  const [mode, setMode] = useState(initialRoute.mode);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [attachments, setAttachments] = useState([]);
  const [toast, setToast] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [memories, setMemories] = useState([]);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryReviewNotice, setMemoryReviewNotice] = useState(null);
  const [memoryFocusId, setMemoryFocusId] = useState(null);
  const [dialog, setDialog] = useState(null);
  const abortRef = useRef(null);
  const activeResearchJobRef = useRef(null);
  const activeAssistantRef = useRef(null);
  const endRef = useRef(null);
  const memoryReviewCount = memories.filter((memory) =>
    ["candidate", "conflict", "stale"].includes(memory.status),
  ).length;
  const isUploading = attachments.some(
    (attachment) => attachment.status === "uploading",
  );

  function showRoute(view, nextMode = mode, { replace = false } = {}) {
    const hash = routeHash(view, nextMode);
    if (window.location.hash !== hash) {
      window.history[replace ? "replaceState" : "pushState"](null, "", hash);
    }
    setActiveView(view);
    setMode(nextMode);
  }

  async function authorizationHeaders(extra = {}) {
    const token = await authSession.getToken();
    return { ...extra, Authorization: `Bearer ${token}` };
  }

  async function loadConversations() {
    try {
      const headers = await authorizationHeaders();
      const [healthResponse, response] = await Promise.all([
        fetch(`${API_BASE}/api/health`),
        fetch(`${API_BASE}/api/conversations`, {
          headers,
        }),
      ]);
      if (!healthResponse.ok || !response.ok)
        throw new Error("API unavailable");
      const payload = await response.json();
      setConversations(payload.conversations);
    } catch {
      setConversations([]);
    }
  }

  async function loadMemories() {
    setMemoryLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/memories`, {
        headers: await authorizationHeaders(),
      });
      if (!response.ok) throw new Error("Memory Ledger unavailable");
      const payload = await response.json();
      setMemories(payload.memories ?? []);
    } catch {
      setToast("The Memory Ledger could not be loaded.");
    } finally {
      setMemoryLoading(false);
    }
  }

  useEffect(() => {
    if (!window.location.hash)
      showRoute(initialRoute.view, initialRoute.mode, { replace: true });
    function syncRoute() {
      const next = routeFromLocation();
      setActiveView(next.view);
      setMode(next.mode);
    }
    window.addEventListener("popstate", syncRoute);
    window.addEventListener("hashchange", syncRoute);
    void loadConversations();
    void loadMemories();
    return () => {
      window.removeEventListener("popstate", syncRoute);
      window.removeEventListener("hashchange", syncRoute);
    };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(""), 2800);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (activeView !== "memory" || memoryLoading || !memoryFocusId) {
      return undefined;
    }
    const timer = setTimeout(() => {
      const target = document.getElementById(`memory-${memoryFocusId}`);
      if (!target) return;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.focus({ preventScroll: true });
    }, 40);
    return () => clearTimeout(timer);
  }, [activeView, memories, memoryFocusId, memoryLoading]);

  function resetConversation() {
    abortRef.current?.abort();
    activeResearchJobRef.current = null;
    activeAssistantRef.current = null;
    setConversationId(null);
    setMessages([]);
    setInput("");
    setAttachments([]);
    showRoute("chat", "chat");
    setSidebarOpen(false);
  }

  async function openConversation(conversation) {
    abortRef.current?.abort();
    activeResearchJobRef.current = null;
    activeAssistantRef.current = null;
    setIsStreaming(false);
    showRoute("chat", mode);
    try {
      const response = await fetch(
        `${API_BASE}/api/conversations/${conversation.id}`,
        { headers: await authorizationHeaders() },
      );
      if (!response.ok) throw new Error("Conversation unavailable");
      const payload = await response.json();
      setConversationId(payload.id);
      showRoute("chat", payload.mode);
      const hydratedMessages = await Promise.all(
        payload.messages.map(async (message) => {
          const baseMessage = {
            id: message.id,
            role: message.role,
            content: message.content,
          };
          if (!message.research_job_id) return baseMessage;
          try {
            const researchResponse = await fetch(
              `${API_BASE}/api/research/${message.research_job_id}`,
              { headers: await authorizationHeaders() },
            );
            if (!researchResponse.ok) return baseMessage;
            const job = await researchResponse.json();
            const retrySnapshot = researchRetrySnapshot(job);
            return {
              ...baseMessage,
              content: job.checkpoint.report || baseMessage.content,
              research: {
                jobId: job.id,
                status: job.status,
                progress: job.progress,
                providerResponseId: job.provider_response_id,
                providerStatus: job.provider_status,
                sources: job.checkpoint.sources,
                citations: job.checkpoint.citations,
                searchRound: job.search_round,
                maxSearchRounds: job.budget?.max_search_rounds,
                completedSubtasks: (job.checkpoint.subtasks ?? []).filter(
                  (task) => task.status === "completed",
                ).length,
                totalSubtasks: (job.checkpoint.subtasks ?? []).length,
                totalToolCalls: job.total_tool_calls,
                maxTotalToolCalls: job.budget?.max_total_tool_calls,
                maxToolCallOverrun: job.budget?.max_tool_call_overrun,
                hardMaxTotalToolCalls:
                  (job.budget?.max_total_tool_calls ?? 0) +
                  (job.budget?.max_tool_call_overrun ?? 0),
                budgetExceeded: job.budget_exceeded,
                hardBudgetReached: job.hard_budget_reached,
                citationCoverage: job.citation_coverage,
                webCitationCoverage: job.web_citation_coverage,
                fileCorroborationCoverage: job.file_corroboration_coverage,
                qualityWarning: job.quality_warning,
                ...retrySnapshot,
                softDeadlineReached: job.soft_deadline_reached,
                degradedReasons: job.degraded_reasons ?? [],
              },
            };
          } catch {
            return baseMessage;
          }
        }),
      );
      setMessages(hydratedMessages);
      setInput("");
      setAttachments([]);
      setSidebarOpen(false);
      const activeMessage = [...hydratedMessages]
        .reverse()
        .find(
          (message) =>
            message.research?.jobId &&
            [
              "queued",
              "planning",
              "collecting",
              "verifying",
              "synthesizing",
            ].includes(message.research.status),
        );
      if (activeMessage) {
        setIsStreaming(true);
        activeResearchJobRef.current = activeMessage.research.jobId;
        void runStreamingRequest({
          endpoint: `/api/research/${activeMessage.research.jobId}/resume`,
          assistantId: activeMessage.id,
        });
      }
    } catch {
      setToast("The conversation could not be opened.");
    }
  }

  function deleteConversation(conversation) {
    setDialog({
      title: "Delete conversation?",
      description: `“${conversation.title}” and all of its messages will be permanently deleted. Any active Research task will also stop.`,
      confirmLabel: "Delete",
      danger: true,
      onConfirm: () => performDeleteConversation(conversation),
    });
  }

  async function performDeleteConversation(conversation) {
    if (conversation.id === conversationId) {
      abortRef.current?.abort();
      setIsStreaming(false);
    }
    try {
      const response = await fetch(
        `${API_BASE}/api/conversations/${conversation.id}`,
        {
          method: "DELETE",
          headers: await authorizationHeaders(),
        },
      );
      if (response.status !== 204) throw new Error("Delete failed");
      setConversations((current) =>
        current.filter((item) => item.id !== conversation.id),
      );
      if (conversation.id === conversationId) resetConversation();
      setToast("Conversation deleted.");
    } catch {
      setToast("The conversation could not be deleted.");
    }
  }

  function deleteAccount() {
    setDialog({
      title: "Delete your account?",
      description:
        "Your Mind account, conversations, memories, and Research jobs will be permanently deleted. This cannot be undone.",
      confirmLabel: "Delete account",
      danger: true,
      onConfirm: performDeleteAccount,
    });
  }

  async function performDeleteAccount() {
    try {
      const response = await fetch(`${API_BASE}/api/account`, {
        method: "DELETE",
        headers: await authorizationHeaders(),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        if (payload?.error?.code === "recent_authentication_required") {
          setToast(
            "For security, sign out and sign in again before deleting your account.",
          );
          return;
        }
        throw new Error(payload?.error?.message || "Account deletion failed.");
      }
      await authSession.logout();
    } catch (error) {
      setToast(
        error.message || "Your account could not be deleted. Please try again.",
      );
    }
  }

  async function createMemory(memory) {
    try {
      const response = await fetch(`${API_BASE}/api/memories`, {
        method: "POST",
        headers: await authorizationHeaders({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify(memory),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok)
        throw new Error(
          payload?.error?.message || "Memory could not be saved.",
        );
      setMemories((current) => [payload, ...current]);
      setToast("Memory added and enabled.");
      return true;
    } catch (error) {
      setToast(error.message || "Memory could not be saved.");
      return false;
    }
  }

  async function confirmMemory(memoryId) {
    const memory = memories.find((item) => item.id === memoryId);
    if (memory?.sensitivity === "sensitive") {
      setDialog({
        title: "Use sensitive memory?",
        description:
          "This memory may contain sensitive personal information. Confirm that Mind may use it in future model requests.",
        confirmLabel: "Confirm memory",
        onConfirm: () => performConfirmMemory(memoryId, memory),
      });
      return;
    }
    await performConfirmMemory(memoryId, memory);
  }

  async function performConfirmMemory(memoryId, memory) {
    try {
      const response = await fetch(
        `${API_BASE}/api/memories/${memoryId}/confirm`,
        {
          method: "POST",
          headers: await authorizationHeaders(),
        },
      );
      if (!response.ok) throw new Error("Memory confirmation failed.");
      await response.json();
      await loadMemories();
      setMemoryFocusId(null);
      setToast(
        memory?.status === "conflict"
          ? "Selected version enabled; the previous version was superseded."
          : memory?.review_reason === "update"
            ? "Memory update applied; the previous version was superseded."
            : "Memory confirmed and enabled.",
      );
    } catch {
      setToast("The memory could not be confirmed.");
    }
  }

  async function updateMemory(memoryId, updates) {
    try {
      const response = await fetch(`${API_BASE}/api/memories/${memoryId}`, {
        method: "PATCH",
        headers: await authorizationHeaders({
          "Content-Type": "application/json",
        }),
        body: JSON.stringify(updates),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok)
        throw new Error(payload?.error?.message || "Memory update failed.");
      setMemories((current) =>
        current.map((item) => (item.id === memoryId ? payload : item)),
      );
      setToast("Memory updated.");
    } catch (error) {
      setToast(error.message || "The memory could not be updated.");
    }
  }

  function deleteMemory(memory) {
    setDialog({
      title: "Delete memory?",
      description:
        "Mind will permanently forget this item. This cannot be undone.",
      confirmLabel: "Delete",
      danger: true,
      onConfirm: () => performDeleteMemory(memory),
    });
  }

  async function performDeleteMemory(memory) {
    try {
      const response = await fetch(`${API_BASE}/api/memories/${memory.id}`, {
        method: "DELETE",
        headers: await authorizationHeaders(),
      });
      if (response.status !== 204) throw new Error("Memory deletion failed.");
      setMemories((current) => current.filter((item) => item.id !== memory.id));
      if (memoryFocusId === memory.id) setMemoryFocusId(null);
      setToast("Memory deleted.");
    } catch {
      setToast("The memory could not be deleted.");
    }
  }

  function updateAssistantMessage(assistantId, update) {
    setMessages((current) =>
      current.map((message) =>
        message.id === assistantId ? update(message) : message,
      ),
    );
  }

  function handleStreamEvent(event, assistantId) {
    if (event.type === "research_started") {
      activeResearchJobRef.current = event.job_id;
      setConversationId(event.conversation_id);
      updateAssistantMessage(assistantId, (message) => ({
        ...message,
        research: {
          ...(message.research ?? {}),
          jobId: event.job_id,
          status: event.status,
          progress: event.progress,
          restarted: event.restarted,
          searchRound: event.search_round,
          maxSearchRounds: event.max_search_rounds,
          completedSubtasks: event.completed_subtasks,
          totalSubtasks: event.total_subtasks,
          totalToolCalls: event.total_tool_calls,
          maxTotalToolCalls: event.max_total_tool_calls,
          maxToolCallOverrun: event.max_tool_call_overrun,
          hardMaxTotalToolCalls: event.hard_max_total_tool_calls,
          budgetExceeded: event.budget_exceeded,
          hardBudgetReached: event.hard_budget_reached,
          citationCoverage: event.citation_coverage,
          webCitationCoverage: event.web_citation_coverage,
          fileCorroborationCoverage: event.file_corroboration_coverage,
          qualityWarning: event.quality_warning,
          recoveryState: event.recovery_state,
          retryAfterSeconds: event.retry_after_seconds,
          softDeadlineReached: event.soft_deadline_reached,
          degradedReasons: event.degraded_reasons ?? [],
        },
      }));
      if (event.restarted) {
        setToast(
          "Started a new research task; the cancelled response was not reused.",
        );
      }
    }
    if (event.type === "status") {
      updateAssistantMessage(assistantId, (message) => ({
        ...message,
        research: {
          ...(message.research ?? {}),
          jobId: event.job_id,
          status: event.status,
          progress: event.progress,
          searchRound: event.search_round,
          maxSearchRounds: event.max_search_rounds,
          completedSubtasks: event.completed_subtasks,
          totalSubtasks: event.total_subtasks,
          totalToolCalls: event.total_tool_calls,
          maxTotalToolCalls: event.max_total_tool_calls,
          maxToolCallOverrun: event.max_tool_call_overrun,
          hardMaxTotalToolCalls: event.hard_max_total_tool_calls,
          budgetExceeded: event.budget_exceeded,
          hardBudgetReached: event.hard_budget_reached,
          citationCoverage: event.citation_coverage,
          webCitationCoverage: event.web_citation_coverage,
          fileCorroborationCoverage: event.file_corroboration_coverage,
          qualityWarning: event.quality_warning,
          recoveryState: event.recovery_state,
          retryAfterSeconds: event.retry_after_seconds,
          softDeadlineReached: event.soft_deadline_reached,
          degradedReasons: event.degraded_reasons ?? [],
        },
      }));
    }
    if (event.type === "source") {
      updateAssistantMessage(assistantId, (message) => {
        const currentSources = message.research?.sources ?? [];
        const sources = currentSources.some(
          (source) => source.id === event.source.id,
        )
          ? currentSources
          : [...currentSources, event.source];
        return {
          ...message,
          research: { ...(message.research ?? {}), sources },
        };
      });
    }
    if (event.type === "delta") {
      updateAssistantMessage(assistantId, (message) => ({
        ...message,
        content: message.content + event.delta,
      }));
    }
    if (event.type === "done") {
      setConversationId(event.conversation_id);
      updateAssistantMessage(assistantId, (message) => ({
        ...message,
        research: message.research
          ? {
              ...message.research,
              status: event.status ?? "completed",
              progress: 1,
              citations: event.citations ?? [],
              totalToolCalls:
                event.total_tool_calls ?? message.research.totalToolCalls,
              maxTotalToolCalls:
                event.max_total_tool_calls ??
                message.research.maxTotalToolCalls,
              maxToolCallOverrun:
                event.max_tool_call_overrun ??
                message.research.maxToolCallOverrun,
              hardMaxTotalToolCalls:
                event.hard_max_total_tool_calls ??
                message.research.hardMaxTotalToolCalls,
              budgetExceeded:
                event.budget_exceeded ?? message.research.budgetExceeded,
              hardBudgetReached:
                event.hard_budget_reached ?? message.research.hardBudgetReached,
              citationCoverage:
                event.citation_coverage ?? message.research.citationCoverage,
              webCitationCoverage:
                event.web_citation_coverage ??
                message.research.webCitationCoverage,
              fileCorroborationCoverage:
                event.file_corroboration_coverage ??
                message.research.fileCorroborationCoverage,
              qualityWarning:
                event.quality_warning ?? message.research.qualityWarning,
              recoveryState: event.recovery_state,
              retryAfterSeconds: event.retry_after_seconds,
              softDeadlineReached:
                event.soft_deadline_reached ??
                message.research.softDeadlineReached,
              degradedReasons:
                event.degraded_reasons ?? message.research.degradedReasons,
            }
          : message.research,
      }));
      if ((event.memory_candidate_count ?? 0) > 0) {
        const candidates = Array.isArray(event.memory_candidates)
          ? event.memory_candidates
          : [];
        setMemoryReviewNotice({
          candidates,
          count: event.memory_candidate_count,
        });
        void loadMemories();
      } else if ((event.memory_saved_count ?? 0) > 0) {
        setToast(
          `${event.memory_saved_count} explicit memory update${
            event.memory_saved_count === 1 ? " was" : "s were"
          } saved.`,
        );
      }
    }
    if (event.type === "error") {
      updateAssistantMessage(assistantId, (message) => ({
        ...message,
        content: event.message,
        research: message.research
          ? { ...message.research, status: "failed" }
          : message.research,
      }));
      setToast(
        event.retryable
          ? "Research paused. Retry to recover or restart the task."
          : "Check the Research configuration before retrying.",
      );
    }
  }

  async function runStreamingRequest({ endpoint, body, assistantId }) {
    const controller = new AbortController();
    abortRef.current = controller;
    activeAssistantRef.current = assistantId;
    try {
      const response = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: await authorizationHeaders({
          Accept: "text/event-stream",
          ...(body ? { "Content-Type": "application/json" } : {}),
        }),
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
      await readSseStream(response, (event) =>
        handleStreamEvent(event, assistantId),
      );
      setAttachments([]);
      await loadConversations();
    } catch (error) {
      if (error.name !== "AbortError") {
        const publicMessage = error.isApiError
          ? error.message
          : "Mind could not complete the request. Check the API connection, then try again.";
        updateAssistantMessage(assistantId, (message) => ({
          ...message,
          content: message.research
            ? message.content || publicMessage
            : publicMessage,
        }));
        setToast(
          "Connection interrupted. Reopen the conversation to restore the research task.",
        );
      }
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
      activeResearchJobRef.current = null;
      activeAssistantRef.current = null;
    }
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || isStreaming || isUploading) return;

    const isResearch = mode === "research";
    const userMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    };
    const assistantId = crypto.randomUUID();
    setMessages((current) => [
      ...current,
      userMessage,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        research: isResearch
          ? { status: "queued", progress: 0, sources: [], citations: [] }
          : null,
      },
    ]);
    setInput("");
    setIsStreaming(true);
    await runStreamingRequest({
      endpoint: isResearch ? "/api/research" : "/api/chat",
      body: isResearch
        ? {
            conversation_id: conversationId,
            query: text,
            attachment_ids: attachments.map((file) => file.id),
          }
        : {
            conversation_id: conversationId,
            message: text,
            mode,
            attachment_ids: attachments.map((file) => file.id),
          },
      assistantId,
    });
  }

  async function resumeResearch(assistantId, jobId) {
    if (!jobId || isStreaming) return;
    updateAssistantMessage(assistantId, (message) => ({
      ...message,
      content: "",
      research: { ...message.research, status: "queued" },
    }));
    setIsStreaming(true);
    activeResearchJobRef.current = jobId;
    await runStreamingRequest({
      endpoint: `/api/research/${jobId}/resume`,
      assistantId,
    });
  }

  async function stopStreaming() {
    const jobId = activeResearchJobRef.current;
    const assistantId = activeAssistantRef.current;
    abortRef.current?.abort();
    if (jobId) {
      try {
        const response = await fetch(
          `${API_BASE}/api/research/${jobId}/cancel`,
          {
            method: "POST",
            headers: await authorizationHeaders(),
          },
        );
        if (response.ok && assistantId) {
          updateAssistantMessage(assistantId, (message) => ({
            ...message,
            research: { ...message.research, status: "cancelled" },
          }));
        }
      } catch {
        setToast(
          "The stream stopped, but the research status could not be updated.",
        );
      }
    }
    setIsStreaming(false);
    setToast(
      jobId
        ? "Research stopped. Restarting will create a new task."
        : "Generation stopped.",
    );
  }

  async function stageFiles(event) {
    const selected = [...event.target.files];
    event.target.value = "";
    const availableSlots = Math.max(0, 5 - attachments.length);
    const files = selected.slice(0, availableSlots);
    if (!files.length) {
      if (selected.length) setToast("Attach at most 5 files to one request.");
      return;
    }
    const staged = files.map((file) => ({
      localId: crypto.randomUUID(),
      name: file.name,
      size_bytes: file.size,
      status: "uploading",
      source: file,
    }));
    setAttachments((current) => [...current, ...staged]);
    if (selected.length > files.length) {
      setToast("Only the first available files were added; the limit is 5.");
    }

    await Promise.all(
      staged.map(async (item) => {
        try {
          const headers = await authorizationHeaders({
            "Content-Type": item.source.type || "application/octet-stream",
          });
          const response = await fetch(
            `${API_BASE}/api/files?name=${encodeURIComponent(item.name)}`,
            { method: "POST", headers, body: item.source },
          );
          const payload = await response.json().catch(() => null);
          if (!response.ok) {
            throw new Error(
              payload?.error?.message || "The file could not be uploaded.",
            );
          }
          setAttachments((current) =>
            current.map((attachment) =>
              attachment.localId === item.localId
                ? { ...payload, localId: item.localId }
                : attachment,
            ),
          );
        } catch (error) {
          setAttachments((current) =>
            current.filter(
              (attachment) => attachment.localId !== item.localId,
            ),
          );
          setToast(error.message || "The file could not be uploaded.");
        }
      }),
    );
  }

  async function removeAttachment(attachment) {
    if (attachment.status === "uploading") return;
    setAttachments((current) =>
      current.filter((item) => item.localId !== attachment.localId),
    );
    if (!attachment.id) return;
    try {
      const response = await fetch(`${API_BASE}/api/files/${attachment.id}`, {
        method: "DELETE",
        headers: await authorizationHeaders(),
      });
      if (!response.ok && response.status !== 404) {
        throw new Error("The file could not be removed.");
      }
    } catch {
      setAttachments((current) =>
        current.some((item) => item.localId === attachment.localId)
          ? current
          : [...current, attachment],
      );
      setToast("The attachment could not be removed. Try again.");
    }
  }

  const composerProps = {
    value: input,
    onChange: setInput,
    onSend: sendMessage,
    onStop: stopStreaming,
    isStreaming,
    mode,
    onModeChange: (nextMode) => showRoute("chat", nextMode),
    attachments,
    onFiles: stageFiles,
    onRemoveFile: removeAttachment,
    isUploading,
    onVoice: () => setToast("Voice input is planned for a later phase."),
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

  async function openMemoryReview() {
    const targetId = memoryReviewNotice?.candidates?.[0]?.id ?? null;
    abortRef.current?.abort();
    setIsStreaming(false);
    setMemoryFocusId(targetId);
    setMemoryReviewNotice(null);
    showRoute("memory", "chat");
    setSidebarOpen(false);
    await loadMemories();
  }

  function navigate(item) {
    setSidebarOpen(false);
    if (item.view === "heartbeats") {
      setToast("Heartbeats arrive in the next phase.");
      return;
    }
    if (item.view === "memory") {
      abortRef.current?.abort();
      setIsStreaming(false);
      setMemoryFocusId(null);
      setMemoryReviewNotice(null);
      showRoute("memory", "chat");
      void loadMemories();
      return;
    }
    showRoute("chat", item.mode ?? "chat");
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
        currentUser: authSession.user,
        activeView,
        onCollapse: collapseSidebar,
        onNewChat: resetConversation,
        onOpenConversation: openConversation,
        onDeleteConversation: deleteConversation,
        onDeleteAccount:
          authService.mode === "firebase" ? deleteAccount : undefined,
        onSignOut:
          authService.mode === "firebase"
            ? () => authSession.logout()
            : undefined,
        onNavigate: navigate,
        memoryReviewCount,
      }),
    ),
    h(
      "main",
      { className: "main-panel" },
      h(Header, {
        sidebarCollapsed,
        onToggleSidebar: openSidebar,
      }),
      activeView === "memory"
        ? h(MemoryLedger, {
            memories,
            loading: memoryLoading,
            focusId: memoryFocusId,
            onRefresh: loadMemories,
            onCreate: createMemory,
            onConfirm: confirmMemory,
            onUpdate: updateMemory,
            onDelete: deleteMemory,
          })
        : h(
            "div",
            { className: `workspace${messages.length ? " has-messages" : ""}` },
            messages.length
              ? h(
                  "div",
                  { className: "conversation-workspace" },
                  h(Conversation, {
                    messages,
                    endRef,
                    onResumeResearch: resumeResearch,
                  }),
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
    memoryReviewNotice
      ? h(MemoryReviewNotice, {
          notice: memoryReviewNotice,
          onReview: openMemoryReview,
          onDismiss: () => setMemoryReviewNotice(null),
        })
      : null,
    dialog
      ? h(AppDialog, {
          ...dialog,
          onCancel: () => setDialog(null),
        })
      : null,
    toast ? h("div", { className: "toast", role: "status" }, toast) : null,
  );
}

function ConfigurationError({ message }) {
  return h(
    "main",
    { className: "auth-page" },
    h(
      "section",
      { className: "auth-card verification-card" },
      h(
        "span",
        { className: "verification-icon error" },
        h(Icon, { name: "warning" }),
      ),
      h("h1", null, "Firebase configuration needed"),
      h("p", null, message),
    ),
  );
}

function Root() {
  const [authState, setAuthState] = useState({ loading: true, user: null });

  useEffect(() => {
    if (!authService.configured) {
      setAuthState({ loading: false, user: null });
      return undefined;
    }
    return authService.subscribe((user) => {
      setAuthState({ loading: false, user });
    });
  }, []);

  if (!authService.configured) {
    return h(ConfigurationError, { message: authService.configurationError });
  }
  if (authState.loading) {
    return h("main", { className: "auth-page auth-loading" }, "Opening Mind…");
  }
  if (!authState.user) {
    return h(AuthScreen, { service: authService });
  }
  if (authService.requireVerifiedEmail && !authState.user.emailVerified) {
    return h(VerifyEmailScreen, {
      service: authService,
      user: authState.user,
    });
  }

  return h(App, {
    authSession: {
      user: authState.user,
      getToken: () => authService.getToken(),
      logout: () => authService.logout(),
    },
  });
}

createRoot(document.getElementById("root")).render(h(Root));
