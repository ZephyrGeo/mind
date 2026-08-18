"use strict";

const React = require("react");
const { createRoot } = require("react-dom/client");
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
      const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
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
  currentUser,
  onCollapse,
  onNewChat,
  onOpenConversation,
  onDeleteConversation,
  onDeleteAccount,
  onSignOut,
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
      h(
        "div",
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
        "div",
        { className: "profile-copy" },
        h(
          "strong",
          null,
          currentUser?.displayName || currentUser?.email || "Local developer",
        ),
        h(
          "span",
          null,
          currentUser?.email ? "Private Firebase workspace" : "Private workspace",
        ),
      ),
      onDeleteAccount
        ? h(
            "button",
            {
              className: "icon-button ghost danger",
              type: "button",
              onClick: onDeleteAccount,
              "aria-label": "Delete account",
              title: "Delete account",
            },
            h(Icon, { name: "user-minus" }),
          )
        : null,
      onSignOut
        ? h(
            "button",
            {
              className: "icon-button ghost",
              type: "button",
              onClick: onSignOut,
              "aria-label": "Sign out",
              title: "Sign out",
            },
            h(Icon, { name: "sign-out" }),
          )
        : null,
    ),
  );
}

function Header({
  apiState,
  conversationTitle,
  mode,
  providerInfo,
  sidebarCollapsed,
  onToggleSidebar,
  onProviderInfo,
}) {
  const providerDetail =
    mode === "research"
      ? `OpenAI Research Provider · ${
          providerInfo.researchMode === "live"
            ? "ready · calls may incur cost"
            : "needs OPENAI_API_KEY"
        }`
      : providerInfo.billable
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
            mode === "research"
              ? providerInfo.researchMode === "live"
                ? "OpenAI research"
                : "OpenAI key needed"
              : providerInfo.billable
                ? "DeepSeek model"
                : "Local model",
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

function ResearchProgress({ research, onResume }) {
  if (!research) return null;
  const progress = Math.round((research.progress ?? 0) * 100);
  const canResume = ["failed", "cancelled"].includes(research.status);
  const sources = research.sources ?? [];
  const stageIndex = researchStages.findIndex(
    (stage) => stage.status === research.status,
  );
  const currentStage = research.status === "queued" ? 0 : stageIndex;
  const completedAll = research.status === "completed";
  const active = !["completed", "failed", "cancelled"].includes(research.status);
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
    ((research.maxTotalToolCalls ?? 0) +
      (research.maxToolCallOverrun ?? 0));
  const hardBudgetReached =
    research.hardBudgetReached ||
    (hardMaxTotalToolCalls > 0 &&
      (research.totalToolCalls ?? 0) >= hardMaxTotalToolCalls);
  const budgetWarning = hardBudgetReached
    ? `Research budget limit reached (${research.totalToolCalls ?? 0}/${hardMaxTotalToolCalls}); search stopped and synthesis is limited to the evidence collected.`
    : research.budgetExceeded
      ? `Used extra search budget (${research.totalToolCalls ?? 0}/${research.maxTotalToolCalls}); no new searches will be started.`
      : null;

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
          name: research.status === "completed" ? "check-circle" : "spinner-gap",
        }),
        researchStatusLabels[research.status] ?? "Preparing research",
      ),
      h("span", null, `OpenAI · ${progress}%`),
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
      budgetWarning
        ? h(
            "span",
            { className: "research-budget-warning" },
            budgetWarning,
          )
        : active
          ? h("span", null, "This can take several minutes.")
          : null,
    ),
    sources.length
      ? h(
          "div",
          { className: "research-sources" },
          h("strong", null, `${sources.length} sources collected`),
          h(
            "div",
            { className: "research-source-list" },
            sources.map((source) =>
              h(
                "a",
                {
                  key: source.id,
                  href: source.url,
                  target: "_blank",
                  rel: "noreferrer noopener",
                  title: source.snippet || source.title,
                },
                h("span", null, source.id),
                source.title,
                h(Icon, { name: "arrow-square-out" }),
              ),
            ),
          ),
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
            ? "Restart as a new OpenAI task"
            : "Resume OpenAI research",
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

function friendlyAuthError(error) {
  const code = error?.code ?? "";
  if (code.includes("invalid-credential")) return "Email or password is incorrect.";
  if (code.includes("email-already-in-use")) return "An account already uses this email.";
  if (code.includes("weak-password")) return "Use a password with at least six characters.";
  if (code.includes("invalid-email")) return "Enter a valid email address.";
  if (code.includes("too-many-requests")) return "Too many attempts. Please wait and retry.";
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
          h(Icon, { name: "star-four", weight: "fill" }),
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
                autoComplete: view === "register" ? "new-password" : "current-password",
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
      h("span", { className: "verification-icon" }, h(Icon, { name: "envelope" })),
      h("h1", null, "Verify your email"),
      h("p", null, `We sent a verification link to ${user.email}.`),
      feedback ? h("p", { className: "auth-feedback success" }, feedback) : null,
      h(
        "button",
        {
          className: "auth-submit",
          type: "button",
          disabled: busy,
          onClick: () => run(() => service.refreshUser(), "Verification status refreshed."),
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
            onClick: () => run(() => service.resendVerification(), "Verification email sent again."),
          },
          "Resend email",
        ),
        h("button", { type: "button", onClick: () => service.logout() }, "Sign out"),
      ),
    ),
  );
}

function App({ authSession }) {
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
  const [providerInfo, setProviderInfo] = useState({
    name: "fake",
    billable: false,
    researchName: "openai",
    researchBillable: true,
    researchMode: "unavailable",
  });
  const abortRef = useRef(null);
  const activeResearchJobRef = useRef(null);
  const activeAssistantRef = useRef(null);
  const endRef = useRef(null);

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
      if (!healthResponse.ok || !response.ok) throw new Error("API unavailable");
      const [health, payload] = await Promise.all([
        healthResponse.json(),
        response.json(),
      ]);
      setConversations(payload.conversations);
      setProviderInfo({
        name: health.provider,
        billable: health.billable_model_calls,
        researchName: health.research_provider,
        researchBillable: health.billable_research_calls,
        researchMode: health.research_mode,
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
    activeResearchJobRef.current = null;
    activeAssistantRef.current = null;
    setConversationId(null);
    setConversationTitle("New conversation");
    setMessages([]);
    setInput("");
    setAttachments([]);
    setSidebarOpen(false);
  }

  async function openConversation(conversation) {
    abortRef.current?.abort();
    activeResearchJobRef.current = null;
    activeAssistantRef.current = null;
    setIsStreaming(false);
    setApiState("checking");
    try {
      const response = await fetch(
        `${API_BASE}/api/conversations/${conversation.id}`,
        { headers: await authorizationHeaders() },
      );
      if (!response.ok) throw new Error("Conversation unavailable");
      const payload = await response.json();
      setConversationId(payload.id);
      setConversationTitle(payload.title);
      setMode(payload.mode);
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
      setApiState("online");
      const activeMessage = [...hydratedMessages]
        .reverse()
        .find(
          (message) =>
            message.research?.jobId &&
            ["queued", "planning", "collecting", "verifying", "synthesizing"].includes(
              message.research.status,
            ),
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
      setApiState("offline");
      setToast("The conversation could not be opened.");
    }
  }

  async function deleteConversation(conversation) {
    const confirmed = window.confirm(
      `Delete “${conversation.title}”? Any active Research task will be stopped and all messages will be permanently removed. This cannot be undone.`,
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
          headers: await authorizationHeaders(),
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

  async function deleteAccount() {
    const confirmed = window.confirm(
      "Delete your Mind account and all conversations and Research jobs? This cannot be undone.",
    );
    if (!confirmed) return;

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
        },
      }));
      if (event.restarted) {
        setToast("Started a new OpenAI research task; the cancelled response was not reused.");
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
        },
      }));
    }
    if (event.type === "source") {
      updateAssistantMessage(assistantId, (message) => {
        const currentSources = message.research?.sources ?? [];
        const sources = currentSources.some((source) => source.id === event.source.id)
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
                event.max_total_tool_calls ?? message.research.maxTotalToolCalls,
              maxToolCallOverrun:
                event.max_tool_call_overrun ??
                message.research.maxToolCallOverrun,
              hardMaxTotalToolCalls:
                event.hard_max_total_tool_calls ??
                message.research.hardMaxTotalToolCalls,
              budgetExceeded:
                event.budget_exceeded ?? message.research.budgetExceeded,
              hardBudgetReached:
                event.hard_budget_reached ??
                message.research.hardBudgetReached,
            }
          : message.research,
      }));
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
          ? "OpenAI research paused. Retry to recover or restart the task."
          : "Check the OpenAI Research configuration before retrying.",
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
      setApiState("online");
      await readSseStream(response, (event) => handleStreamEvent(event, assistantId));
      setAttachments([]);
      await loadConversations();
    } catch (error) {
      if (error.name !== "AbortError") {
        setApiState("offline");
        const publicMessage = error.isApiError
          ? error.message
          : "Mind could not complete the request. Check the API connection, then try again.";
        updateAssistantMessage(assistantId, (message) => ({
          ...message,
          content: message.research ? message.content || publicMessage : publicMessage,
        }));
        setToast(
          "Connection interrupted. Reopen the conversation to restore the OpenAI research task.",
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
    if (!text || isStreaming) return;

    const isResearch = mode === "research";
    const userMessage = { id: crypto.randomUUID(), role: "user", content: text };
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
    if (!conversationId) {
      setConversationTitle(text.replace(/\s+/g, " ").slice(0, 56));
    }
    setIsStreaming(true);
    setApiState("checking");

    await runStreamingRequest({
      endpoint: isResearch ? "/api/research" : "/api/chat",
      body: isResearch
        ? { conversation_id: conversationId, query: text }
        : {
            conversation_id: conversationId,
            message: text,
            mode,
            attachments: attachments.map((file) => ({
              name: file.name,
              size: file.size,
            })),
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
    setApiState("checking");
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
        const response = await fetch(`${API_BASE}/api/research/${jobId}/cancel`, {
          method: "POST",
          headers: await authorizationHeaders(),
        });
        if (response.ok && assistantId) {
          updateAssistantMessage(assistantId, (message) => ({
            ...message,
            research: { ...message.research, status: "cancelled" },
          }));
        }
      } catch {
        setToast("The stream stopped, but the research status could not be updated.");
      }
    }
    setIsStreaming(false);
    setToast(
      jobId
        ? "Research stopped. Restarting will create a new OpenAI task."
        : "Generation stopped.",
    );
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
        currentUser: authSession.user,
        onCollapse: collapseSidebar,
        onNewChat: resetConversation,
        onOpenConversation: openConversation,
        onDeleteConversation: deleteConversation,
        onDeleteAccount:
          authService.mode === "firebase" ? deleteAccount : undefined,
        onSignOut:
          authService.mode === "firebase" ? () => authSession.logout() : undefined,
      }),
    ),
    h(
      "main",
      { className: "main-panel" },
      h(Header, {
        apiState,
        conversationTitle,
        mode,
        providerInfo,
        sidebarCollapsed,
        onToggleSidebar: openSidebar,
        onProviderInfo: () =>
          setToast(
            `Chat: ${providerInfo.billable ? "DeepSeek" : "Fake model"} · Research: OpenAI ${
              providerInfo.researchMode === "live" ? "ready" : "needs OPENAI_API_KEY"
            }`,
          ),
      }),
      h(
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
      h("span", { className: "verification-icon error" }, h(Icon, { name: "warning" })),
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
