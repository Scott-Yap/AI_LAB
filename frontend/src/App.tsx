import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  BookOpen,
  ChevronDown,
  CircleHelp,
  History,
  MessageSquare,
  Plus,
  Settings as SettingsIcon,
  Square,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, streamMessage } from "./api";
import { KnowledgeGraph } from "./KnowledgeGraph";
import { SettingsDialog } from "./SettingsDialog";
import { useAppearance } from "./appearance";
import { runtimeStatus } from "./runtimeStatus";
import type {
  Concept,
  Conversation,
  Graph,
  Health,
  IndexStatus,
  Message,
  Settings,
  Source,
} from "./types";

const initialSettings = { instructions: "", think: false };
function SourceCards({ sources }: { sources: Source[] }) {
  const unique = [
    ...new Map(sources.map((s) => [`${s.chapter}:${s.section}`, s])).values(),
  ];
  return (
    unique.length > 0 && (
      <div className="sources">
        <span className="eyebrow">
          <BookOpen size={12} /> TEXTBOOK CONTEXT RETRIEVED
        </span>
        {unique.map((source) => (
          <details key={source.chunk_id}>
            <summary>
              {source.section}
              <ChevronDown size={13} />
            </summary>
            <p>
              {source.chapter}
              <br />
              {source.title}
            </p>
            <small>
              Source: {source.source_id} · Chunk {source.chunk_id}
            </small>
          </details>
        ))}
      </div>
    )
  );
}

export default function App() {
  const { appearance, changeAppearance } = useAppearance();
  const [settings, setSettings] = useState<Settings>(initialSettings);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [graph, setGraph] = useState<Graph>({ nodes: [], edges: [] });
  const [selected, setSelected] = useState<Concept | null>(null);
  const [index, setIndex] = useState<IndexStatus | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");
  const controller = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const [showScroll, setShowScroll] = useState(false);
  const composer = useRef<HTMLTextAreaElement>(null);
  const pendingSavedResponse = messages.some(
    (message) => message.status === "streaming",
  );

  const refreshStatus = useCallback(async () => {
    const [nextIndex, nextHealth] = await Promise.all([
      api<IndexStatus>("/textbook/status"),
      api<Health>("/health"),
    ]);
    setIndex(nextIndex);
    setHealth(nextHealth);
  }, []);
  const initialize = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [s, c, g] = await Promise.all([
        api<Settings>("/settings"),
        api<Conversation[]>("/conversations"),
        api<Graph>("/graph"),
      ]);
      setSettings(s);
      setConversations(c);
      setGraph(g);
      if (c.length) {
        setActive(c[0].id);
        setMessages(await api<Message[]>(`/conversations/${c[0].id}/messages`));
      }
      await refreshStatus();
      setReady(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [refreshStatus]);
  useEffect(() => {
    void initialize();
    return () => controller.current?.abort();
  }, [initialize]);
  useEffect(() => {
    const timer = window.setInterval(
      () => void refreshStatus().catch(() => setHealth(null)),
      index?.state === "indexing" ? 2000 : 15000,
    );
    return () => clearInterval(timer);
  }, [refreshStatus, index?.state]);
  useEffect(() => {
    if (follow.current && scroll.current)
      scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [messages, status]);
  useEffect(() => {
    // Cancellation may reach FastAPI just after our first history refresh.
    // Also recover a page reopened while a response is still being finalized.
    if (busy || !active || !pendingSavedResponse) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const saved = await api<Message[]>(`/conversations/${active}/messages`);
        if (!cancelled && !inFlight.current) setMessages(saved);
      } catch {
        if (!cancelled)
          setError(
            "Cannot refresh the response. Check the backend connection.",
          );
      }
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [busy, active, pendingSavedResponse]);

  async function chooseConversation(id: string) {
    if (inFlight.current) return;
    setLoading(true);
    setError("");
    setHistoryOpen(false);
    try {
      const next = await api<Message[]>(`/conversations/${id}/messages`);
      setActive(id);
      setMessages(next);
      follow.current = true;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  function newConversation() {
    if (!inFlight.current) {
      setActive(null);
      setMessages([]);
      setInput("");
      setError("");
      setWarning("");
      setHistoryOpen(false);
      composer.current?.focus();
    }
  }
  async function toggleThink() {
    const next = { ...settings, think: !settings.think };
    try {
      setSettings(
        await api<Settings>("/settings", {
          method: "PUT",
          body: JSON.stringify(next),
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function send(text = input, retry = false) {
    if (
      !text.trim() ||
      inFlight.current ||
      pendingSavedResponse ||
      loading ||
      !ready
    )
      return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setWarning("");
    setStatus("Connecting…");
    follow.current = true;
    const aborter = new AbortController();
    controller.current = aborter;
    let id = active,
      assistantId = "";
    try {
      if (!id) {
        const conversation = await api<Conversation>("/conversations", {
          method: "POST",
        });
        id = conversation.id;
        setActive(id);
      }
      if (!retry) {
        setInput("");
        setMessages((old) => [
          ...old,
          {
            id: crypto.randomUUID(),
            role: "user",
            content: text,
            sources: [],
            status: "complete",
            think: settings.think,
          },
        ]);
      }
      await streamMessage(
        id,
        text,
        settings.think,
        retry,
        aborter.signal,
        (event) => {
          if (event.type === "start") {
            assistantId = event.message.id;
            setMessages((old) => [...old, event.message]);
          } else if (event.type === "status") setStatus(event.message);
          else if (event.type === "warning") setWarning(event.message);
          else if (event.type === "error") setError(event.message);
          else if (event.type !== "done")
            setMessages((old) =>
              old.map((m) =>
                m.id !== assistantId
                  ? m
                  : event.type === "token"
                    ? { ...m, content: m.content + event.text }
                    : event.type === "reset"
                      ? { ...m, content: "" }
                      : { ...m, sources: event.sources },
              ),
            );
        },
      );
    } catch (e) {
      setError(
        aborter.signal.aborted ? "Response stopped." : (e as Error).message,
      );
    } finally {
      if (id) {
        try {
          setMessages(await api<Message[]>(`/conversations/${id}/messages`));
          setConversations(await api<Conversation[]>("/conversations"));
        } catch {
          setError(
            "Cannot refresh the conversation. Check the backend connection.",
          );
          if (!assistantId) setInput(text);
        }
      }
      inFlight.current = false;
      setBusy(false);
      setStatus("");
      controller.current = null;
    }
  }
  function learn(concept: Concept) {
    void send(
      `Teach me ${concept.name.toLowerCase()} using the textbook. Start with one focused question to check what I already understand.`,
    );
  }
  async function rebuild() {
    await api("/textbook/index?force=true", { method: "POST" });
    await refreshStatus();
  }
  const last = messages.at(-1);
  const canRetry =
    last?.role === "assistant" &&
    ["error", "interrupted"].includes(last.status);
  const lastUser = [...messages]
    .reverse()
    .find((m) => m.role === "user")?.content;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">✳</span>
          <span>
            AI Lab<span className="brand-divider">/</span>
            <span className="brand-sub">A space to understand.</span>
          </span>
        </div>
        <div className="header-actions">
          <span
            className={`local-badge ${health?.reachable && health.model_loaded && health.embedding_loaded ? "" : "offline"}`}
            title="Loaded means resident in memory, not actively generating. Unloaded installed models load automatically when needed. Status refreshes every 15 seconds."
          >
            <i />
            {runtimeStatus(health)}
          </span>
          <button
            className="icon-button"
            title="Tutor settings"
            aria-label="Open Tutor Settings"
            disabled={!ready}
            onClick={() => setSettingsOpen(true)}
          >
            <SettingsIcon size={19} />
          </button>
        </div>
      </header>
      <main className="workspace">
        <KnowledgeGraph
          graph={graph}
          selected={selected}
          onSelect={setSelected}
          onLearn={learn}
          busy={busy || pendingSavedResponse || loading || !ready}
        />
        <section className="chat-panel" aria-label="Tutor chat">
          <div className="chat-heading">
            <div className="tutor-heading">
              <div className="tutor-icon">
                <BookOpen size={20} />
              </div>
              <div>
                <h1>AI Engineering Tutor</h1>
                <span>Understand deeply. Build thoughtfully.</span>
              </div>
            </div>
            <div className="chat-actions">
              <button
                title="Previous conversations"
                aria-label="Previous conversations"
                disabled={busy || loading}
                onClick={() => setHistoryOpen(!historyOpen)}
              >
                <History size={19} />
              </button>
              <button
                title="New conversation"
                aria-label="New conversation"
                disabled={busy || loading}
                onClick={newConversation}
              >
                <Plus size={21} />
              </button>
            </div>
          </div>
          {historyOpen && (
            <aside className="history-panel" aria-label="Conversation history">
              <div className="detail-top">
                <strong>Your conversations</strong>
                <button
                  aria-label="Close history"
                  onClick={() => setHistoryOpen(false)}
                >
                  <X size={17} />
                </button>
              </div>
              <button className="secondary" onClick={newConversation}>
                <Plus size={15} />
                New conversation
              </button>
              {conversations.length === 0 && (
                <p className="muted">Your conversations will appear here.</p>
              )}
              {conversations.map((c) => (
                <button
                  className={`history-item ${active === c.id ? "active" : ""}`}
                  key={c.id}
                  onClick={() => void chooseConversation(c.id)}
                >
                  <MessageSquare size={15} />
                  <span>
                    {c.title}
                    <small>{new Date(c.updated_at).toLocaleDateString()}</small>
                  </span>
                </button>
              ))}
            </aside>
          )}
          {ready && index?.state !== "ready" && (
            <button
              className="setup-banner"
              onClick={() => setSettingsOpen(true)}
            >
              <BookOpen size={15} />
              {index?.state === "indexing"
                ? `Preparing your textbook · ${index.progress ?? 0}%`
                : index?.searchable
                  ? "Textbook indexing needs attention · Previous index available"
                  : "Connect your textbook to ground your learning"}
              <ArrowUpRight size={15} />
            </button>
          )}
          <div
            className="messages"
            ref={scroll}
            onScroll={() => {
              const el = scroll.current!;
              follow.current =
                el.scrollHeight - el.scrollTop - el.clientHeight < 90;
              setShowScroll(!follow.current);
            }}
          >
            {loading ? (
              <div className="loading-state">Opening your learning space…</div>
            ) : messages.length === 0 ? (
              <div className="welcome">
                <div className="welcome-art">
                  <span className="orbit orbit-one" />
                  <span className="orbit orbit-two" />
                  <span className="orbit orbit-three" />
                  <span className="orbit-center">✳</span>
                  <i className="satellite one" />
                  <i className="satellite two" />
                </div>
                <span className="eyebrow">CURIOSITY IS A GOOD START</span>
                <h2>
                  Let’s make it
                  <br />
                  <em>make sense.</em>
                </h2>
                <p>
                  Your thinking partner for AI Engineering.
                  <br />
                  Explore an idea, work through a problem, or connect the dots.
                </p>
                <div className="starter-prompts">
                  {[
                    "Why do embeddings capture meaning?",
                    "Help me understand RAG",
                    "Test me on prompt engineering",
                  ].map((prompt) => (
                    <button
                      disabled={!ready}
                      key={prompt}
                      onClick={() => void send(prompt)}
                    >
                      {prompt}
                      <ArrowUpRight size={16} />
                    </button>
                  ))}
                </div>
                <div className="book-credit">
                  <BookOpen size={14} /> Guided by <em>AI Engineering</em> by
                  Chip Huyen
                </div>
              </div>
            ) : (
              messages.map((message, i) => (
                <article className={`message ${message.role}`} key={message.id}>
                  <div className="message-label">
                    {message.role === "assistant" ? (
                      <>
                        <span className="mini-mark">✳</span> TUTOR{" "}
                        {message.think && (
                          <span className="thought-label">Think on</span>
                        )}
                      </>
                    ) : (
                      "YOU"
                    )}
                  </div>
                  <div className="message-content">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        a: ({ children, ...props }) => (
                          <a {...props} target="_blank" rel="noreferrer">
                            {children}
                          </a>
                        ),
                        img: ({ alt }) => <span>[Image: {alt}]</span>,
                      }}
                    >
                      {message.content}
                    </ReactMarkdown>
                    {!message.content && message.status === "streaming" && (
                      <span className="muted">
                        {busy ? status : "Waiting for the saved response…"}
                      </span>
                    )}
                  </div>
                  {message.role === "assistant" && (
                    <SourceCards sources={message.sources} />
                  )}{" "}
                  {message.error && (
                    <p className="inline-error">{message.error}</p>
                  )}
                  {i === messages.length - 1 && canRetry && !busy && (
                    <button
                      className="secondary retry-button"
                      onClick={() => void send(lastUser, true)}
                    >
                      Retry response
                    </button>
                  )}
                </article>
              ))
            )}
          </div>
          {showScroll && (
            <button
              className="scroll-bottom"
              aria-label="Scroll to latest"
              onClick={() => {
                follow.current = true;
                scroll.current?.scrollTo({
                  top: scroll.current.scrollHeight,
                  behavior: "smooth",
                });
              }}
            >
              <ArrowDown size={17} />
            </button>
          )}
          <div className="composer-area">
            {error && (
              <div className="error-banner" role="alert">
                <span>{error}</span>
                {!ready && (
                  <button onClick={() => void initialize()}>
                    Retry connection
                  </button>
                )}
                <button aria-label="Dismiss error" onClick={() => setError("")}>
                  <X size={15} />
                </button>
              </div>
            )}
            {warning && (
              <p className="tool-warning">Textbook search: {warning}</p>
            )}
            {busy && (
              <div className="stream-status" role="status">
                <i />
                {status}
              </div>
            )}
            <form
              className="composer"
              onSubmit={(e) => {
                e.preventDefault();
                void send();
              }}
            >
              <textarea
                ref={composer}
                aria-label="Message the tutor"
                placeholder="What are you curious about?"
                value={input}
                disabled={!ready || loading}
                maxLength={4000}
                rows={2}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (
                    e.key === "Enter" &&
                    !e.shiftKey &&
                    !e.nativeEvent.isComposing
                  ) {
                    e.preventDefault();
                    void send();
                  }
                }}
              />
              <div className="composer-bottom">
                <div
                  className="chat-model-options"
                  aria-label="Chat model options"
                >
                  <BookOpen size={13} /> AI Engineering{" "}
                  <span className="composer-dot" aria-hidden="true">
                    ·
                  </span>
                  <button
                    type="button"
                    className={`think-toggle ${settings.think ? "enabled" : ""}`}
                    role="switch"
                    aria-checked={settings.think}
                    aria-label="Think mode"
                    disabled={!ready || busy}
                    onClick={() => void toggleThink()}
                  >
                    Think <strong>{settings.think ? "ON" : "OFF"}</strong>
                    <span className="toggle-track" aria-hidden="true">
                      <i />
                    </span>
                  </button>
                </div>
                {busy ? (
                  <button
                    type="button"
                    className="send-button"
                    aria-label="Stop response"
                    onClick={() => controller.current?.abort()}
                  >
                    <Square size={14} />
                  </button>
                ) : (
                  <button
                    className="send-button"
                    type="submit"
                    aria-label="Send message"
                    disabled={
                      !input.trim() || !ready || loading || pendingSavedResponse
                    }
                  >
                    <ArrowUp size={19} />
                  </button>
                )}
              </div>
            </form>
            <div className="composer-footnote">
              <span>Understand → Explain → Apply → Retrieve → Connect</span>
              <span title="Local models can make mistakes. Check retrieved sources.">
                <CircleHelp size={13} />
              </span>
            </div>
          </div>
        </section>
      </main>
      <footer className="app-footer">
        <span>
          AI LAB <span className="footer-version">/ TUTOR V1</span>
        </span>
        <span>Local inference. Lasting understanding.</span>
        <span>{health?.model ?? "qwen3.5:9b"}</span>
      </footer>
      {settingsOpen && (
        <SettingsDialog
          settings={settings}
          index={index}
          health={health}
          onClose={() => setSettingsOpen(false)}
          onSave={setSettings}
          onIndex={rebuild}
          appearance={appearance}
          onAppearanceChange={changeAppearance}
        />
      )}
    </div>
  );
}
