import { useEffect, useRef, useState } from "react";
import { LoaderCircle, MessageCircle, Send, Trash2, X } from "lucide-react";
import { localRuleAssistant, type AmbuAssistContext } from "./assistantLogic";

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  text: string;
}

interface AmbuAssistProps {
  context: AmbuAssistContext;
}

const suggestedQuestions = [
  "How do I start?",
  "What is A*?",
  "How do I block a road?",
  "Why did my route change?",
  "Why is no route available?",
  "What does congestion multiplier 2 mean?",
];

export function AmbuAssist({ context }: AmbuAssistProps) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const nextId = useRef(0);
  const conversationVersion = useRef(0);
  const historyEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    historyEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading, open]);

  async function sendQuestion(question = draft) {
    const text = question.trim();
    if (!text || loading) return;
    setDraft("");
    setError("");
    setMessages((current) => [...current, { id: nextId.current++, role: "user", text }]);
    setLoading(true);
    const requestVersion = conversationVersion.current;

    try {
      await new Promise((resolve) => window.setTimeout(resolve, 220));
      const answer = await localRuleAssistant.respond(text, context);
      if (requestVersion === conversationVersion.current) {
        setMessages((current) => [...current, { id: nextId.current++, role: "assistant", text: answer }]);
      }
    } catch {
      if (requestVersion === conversationVersion.current) {
        setError("AmbuAssist couldn’t prepare a reply. Please try again; your route and simulation have not been changed.");
      }
    } finally {
      if (requestVersion === conversationVersion.current) setLoading(false);
    }
  }

  function clearConversation() {
    conversationVersion.current += 1;
    setMessages([]);
    setDraft("");
    setError("");
    setLoading(false);
  }

  return (
    <>
      {open && (
        <section className="ambuassist-panel" aria-label="AmbuAssist chat" aria-modal="false">
          <header className="ambuassist-header">
            <div>
              <strong>AmbuAssist</strong>
              <span>Local navigation guide · not a generative AI</span>
            </div>
            <div className="ambuassist-header-actions">
              <button type="button" onClick={clearConversation} aria-label="Clear conversation" title="Clear conversation">
                <Trash2 size={16} />
              </button>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close AmbuAssist" title="Close">
                <X size={18} />
              </button>
            </div>
          </header>

          <div className="ambuassist-messages" aria-live="polite" aria-relevant="additions">
            {messages.length === 0 && (
              <div className="ambuassist-welcome">
                <strong>Hi, I’m AmbuAssist.</strong>
                <p>Ask how to use the planner or ask me to explain its current route and simulation results. I answer locally using the app’s current state.</p>
              </div>
            )}
            {messages.map((message) => (
              <article className={`ambuassist-message ${message.role}`} key={message.id}>
                <span className="ambuassist-sender">{message.role === "user" ? "You" : "AmbuAssist"}</span>
                <p>{message.text}</p>
              </article>
            ))}
            {loading && (
              <div className="ambuassist-loading" role="status">
                <LoaderCircle size={16} className="ambuassist-spinner" /> Checking the current app state…
              </div>
            )}
            {error && <div className="ambuassist-error" role="alert">{error}</div>}
            <div ref={historyEnd} />
          </div>

          <div className="ambuassist-suggestions" aria-label="Suggested questions">
            {suggestedQuestions.map((suggestion) => (
              <button
                type="button"
                key={suggestion}
                disabled={loading}
                onClick={() => void sendQuestion(suggestion)}
              >
                {suggestion}
              </button>
            ))}
          </div>

          <form
            className="ambuassist-compose"
            onSubmit={(event) => {
              event.preventDefault();
              void sendQuestion();
            }}
          >
            <input
              aria-label="Ask AmbuAssist a question"
              placeholder="Ask about routes, controls, or results…"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              disabled={loading}
            />
            <button type="submit" aria-label="Send message" disabled={loading || !draft.trim()}>
              <Send size={17} />
            </button>
          </form>
        </section>
      )}

      <button
        type="button"
        className={`ambuassist-launcher ${open ? "open" : ""}`}
        aria-label={open ? "Close AmbuAssist" : "Open AmbuAssist"}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        {open ? <X size={22} /> : <><MessageCircle size={20} /><span>AmbuAssist</span></>}
      </button>
    </>
  );
}
