/**
 * AskYoda — Floating AI chatbot widget.
 * Appears as a fab button in the bottom-right corner, expands into a chat panel.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { askYoda, parseApiError } from "../services/api";
import { useAuth } from "../auth/AuthContext";

export default function AskYoda() {
  const { user } = useAuth();
  const firstName = user?.name?.split(" ")[0] || "Padawan";
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        `Greetings, Jedi ${firstName}! Ask Yoda, you may. Help you with KYBER and synthetic data, I will. Hmm, yes.`,
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    if (open) {
      scrollToBottom();
      inputRef.current?.focus();
    }
  }, [open, messages, scrollToBottom]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg = { role: "user", content: text };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInput("");
    setLoading(true);

    try {
      // Send only user/assistant messages (skip system)
      const chatHistory = updatedMessages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .slice(-10); // keep last 10 for context window
      const res = await askYoda(chatHistory);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.reply },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Hmm, a disturbance in the Force I sense. Error: ${parseApiError(err)}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      {/* Floating Action Button */}
      {!open && (
        <button
          data-tour="tour-ask-yoda"
          onClick={() => setOpen(true)}
          className="fixed bottom-14 right-6 z-50 rounded-full bg-gray-50 dark:bg-[#1b1b1f] hover:scale-105 transition-transform duration-200 drop-shadow-lg flex items-center gap-2 overflow-hidden pl-4 pr-2 py-1.5"
          title="Ask Yoda"
        >
          <span className="text-sm font-semibold text-gray-800 dark:text-white whitespace-nowrap">Ask Yoda</span>
          <img
            src="/baby-yoda-v2.png"
            alt="Ask Yoda"
            className="w-10 h-10 object-contain"
          />
        </button>
      )}

      {/* Chat Panel */}
      {open && (
        <div className="fixed bottom-14 right-6 z-50 w-[380px] max-w-[calc(100vw-2rem)] h-[520px] max-h-[calc(100vh-7rem)] flex flex-col rounded-2xl border border-gray-200 dark:border-[#2e2e32] bg-white dark:bg-[#1b1b1f] shadow-2xl shadow-black/10 dark:shadow-black/40 overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-[#2e2e32] bg-gradient-to-r from-[#00FF9F]/10 to-[#00E6CC]/10 dark:from-[#00FF9F]/5 dark:to-[#00E6CC]/5">
            <div className="flex items-center gap-2">
              <img
                src="/baby-yoda-v2.png"
                alt="Yoda"
                className="w-8 h-8 object-contain rounded-full bg-gray-50 dark:bg-[#1b1b1f] p-0.5"
              />
              <div>
                <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                  Ask Yoda
                </h3>
                <p className="text-xs text-gray-500 dark:text-[rgba(235,235,245,0.6)]">
                  AI-powered assistant
                </p>
              </div>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2e2e32] transition-colors"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[80%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                    msg.role === "user"
                      ? "bg-[#00FF9F]/15 dark:bg-[#00FF9F]/10 text-gray-900 dark:text-white rounded-br-md"
                      : "bg-gray-100 dark:bg-[#202127] text-gray-800 dark:text-[rgba(255,255,245,0.86)] rounded-bl-md"
                  }`}
                >
                  {msg.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-gray-100 dark:bg-[#202127] rounded-2xl rounded-bl-md px-4 py-3">
                  <div className="flex gap-1">
                    <span className="w-2 h-2 rounded-full bg-[#00FF9F] animate-bounce [animation-delay:0ms]" />
                    <span className="w-2 h-2 rounded-full bg-[#00FF9F] animate-bounce [animation-delay:150ms]" />
                    <span className="w-2 h-2 rounded-full bg-[#00FF9F] animate-bounce [animation-delay:300ms]" />
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="border-t border-gray-200 dark:border-[#2e2e32] px-3 py-3">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask Yoda a question..."
                rows={1}
                className="flex-1 resize-none rounded-xl border border-gray-200 dark:border-[#3a3a3e] bg-gray-50 dark:bg-[#202127] px-3.5 py-2.5 text-sm text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-[rgba(235,235,245,0.38)] focus:outline-none focus:ring-2 focus:ring-[#00FF9F]/30 focus:border-[#00FF9F]/50 transition-colors"
                style={{ maxHeight: "80px" }}
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || loading}
                className="flex-shrink-0 w-9 h-9 rounded-xl bg-[#00FF9F] hover:bg-[#00E6CC] disabled:opacity-40 disabled:cursor-not-allowed text-gray-900 flex items-center justify-center transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
