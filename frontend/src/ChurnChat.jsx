import { useEffect, useRef, useState } from "react";
import { MessageCircle, Send, X, Bot, ChevronDown } from "lucide-react";
import { postChat } from "./lib/api";

const SUGGESTIONS = [
  "Which accounts are at Critical risk?",
  "Show me Enterprise accounts with payment risk",
  "Which churners had champion turnover?",
  "What are the top signals driving churn?",
  "List High-risk accounts renewing in 90 days",
  "Top priorities",
  "Waiting on manager",
  "Effective interventions",
  "Explain RFM",
];

function Message({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div className={`chat-message ${isUser ? "chat-user" : "chat-bot"}`}>
      {!isUser && (
        <span className="chat-bot-icon">
          <Bot size={14} />
        </span>
      )}
      <div className="chat-bubble">{msg.content}</div>
    </div>
  );
}

export default function ChurnChat() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([
    {
      role: "bot",
      content:
        "Hi! I can answer questions about your at-risk accounts, churn signals, and portfolio health. Try one of the suggestions below or ask anything.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 120);
    }
  }, [open]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const send = async (question) => {
    const q = (question ?? input).trim();
    if (!q || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: q }]);
    setLoading(true);
    try {
      const { answer } = await postChat(q);
      setMessages((prev) => [...prev, { role: "bot", content: answer }]);
    } catch (err) {
      const detail =
        err.message?.includes("ANTHROPIC_API_KEY")
          ? "ANTHROPIC_API_KEY is not set on the API server. Add it to your environment and restart uvicorn."
          : err.message?.includes("anthropic package")
          ? "Run `pip install anthropic` in the churn-scoring environment, then restart the API."
          : "Couldn't reach the chat endpoint. Is the API running?";
      setMessages((prev) => [
        ...prev,
        { role: "bot", content: `⚠ ${detail}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const showSuggestions =
    messages.length === 1 && !loading;

  return (
    <>
      {/* Floating trigger button */}
      <button
        className={`chat-fab ${open ? "chat-fab-open" : ""}`}
        aria-label={open ? "Close chat" : "Ask about churners"}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown size={20} /> : <MessageCircle size={20} />}
        {!open && <span className="chat-fab-label">Ask AI</span>}
      </button>
      {/* Chat panel */}
      {open && (
        <div className="chat-panel" role="dialog" aria-label="Churn AI chat">
          <div className="chat-header">
            <span className="chat-header-icon">
              <Bot size={16} />
            </span>
            <div>
              <strong>Churn AI</strong>
              <small>Ask about your at-risk accounts</small>
            </div>
            <button
              className="chat-close"
              aria-label="Close chat"
              onClick={() => setOpen(false)}
            >
              <X size={16} />
            </button>
          </div>
          <div className="chat-messages">
            {messages.map((m, i) => (
              <Message key={i} msg={m} />
            ))}
            {showSuggestions && (
              <div className="chat-suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="chat-suggestion" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            )}
            {loading && (
              <div className="chat-message chat-bot">
                <span className="chat-bot-icon">
                  <Bot size={14} />
                </span>
                <div className="chat-bubble chat-typing">
                  <span /><span /><span />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
          <form
            className="chat-input-row"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <input
              ref={inputRef}
              className="chat-input"
              placeholder="Ask about churners…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              disabled={loading}
              aria-label="Chat question"
            />
            <button
              type="submit"
              className="chat-send"
              aria-label="Send"
              disabled={!input.trim() || loading}
            >
              <Send size={15} />
            </button>
          </form>
        </div>
      )}
    </>
  );
}
