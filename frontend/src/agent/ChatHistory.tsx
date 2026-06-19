import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { ChatSummary } from "../api/types";
import { useApp } from "../store";
import { PlusCircleIcon, TrashIcon } from "../components/icons";

/** Past analyst conversations, listed in the left sidebar (ChatGPT-style). Click
 *  one to reopen it; double-click the title to rename; "New" starts fresh. */
export function ChatHistory() {
  const { openChat, newChat, openChatId, chatsVersion, refreshChats } = useApp();
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    api
      .listChats()
      .then(setChats)
      .catch(() => setChats([]));
  }, [chatsVersion]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? chats.filter((c) => c.title.toLowerCase().includes(q)) : chats;
  }, [chats, query]);

  async function remove(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    await api.deleteChat(id).catch(() => {});
    if (id === openChatId) newChat();
    refreshChats();
  }

  function startRename(e: React.MouseEvent, c: ChatSummary) {
    e.stopPropagation();
    setEditingId(c.id);
    setDraft(c.title);
  }
  async function commitRename(id: string) {
    const title = draft.trim();
    setEditingId(null);
    if (!title) return;
    setChats((cs) => cs.map((c) => (c.id === id ? { ...c, title } : c)));
    await api.renameChat(id, title).catch(() => {});
    refreshChats();
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col px-3 pt-4">
      <div className="mb-1 flex items-center justify-between px-2">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
          Chats
        </span>
        <button
          onClick={newChat}
          title="New chat"
          className="flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium text-indigo-600 transition hover:bg-indigo-50"
        >
          <PlusCircleIcon className="h-4 w-4" /> New
        </button>
      </div>

      {chats.length > 3 && (
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search chats…"
          className="mb-1 w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[12px] outline-none focus:border-indigo-300"
        />
      )}

      <div className="min-h-0 flex-1 space-y-0.5 overflow-auto">
        {filtered.length === 0 ? (
          <p className="px-2 py-1 text-[11px] text-slate-400">
            {chats.length === 0 ? "No saved chats yet." : "No chats match."}
          </p>
        ) : (
          filtered.map((c) =>
            editingId === c.id ? (
              <input
                key={c.id}
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => commitRename(c.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename(c.id);
                  if (e.key === "Escape") setEditingId(null);
                }}
                className="w-full rounded-lg border border-indigo-300 px-2 py-1.5 text-[13px] outline-none"
              />
            ) : (
              <button
                key={c.id}
                onClick={() => openChat(c.id)}
                onDoubleClick={(e) => startRename(e, c)}
                title={c.title}
                className={`group flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-[13px] transition ${
                  c.id === openChatId
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <span className="flex-1 truncate">{c.title}</span>
                <span
                  role="button"
                  tabIndex={-1}
                  onClick={(e) => startRename(e, c)}
                  title="Rename"
                  className="shrink-0 rounded p-0.5 text-slate-300 opacity-0 transition hover:text-slate-600 group-hover:opacity-100"
                >
                  <PencilIcon />
                </span>
                <span
                  role="button"
                  tabIndex={-1}
                  onClick={(e) => remove(e, c.id)}
                  title="Delete chat"
                  className="shrink-0 rounded p-0.5 text-slate-300 opacity-0 transition hover:text-red-500 group-hover:opacity-100"
                >
                  <TrashIcon className="h-3.5 w-3.5" />
                </span>
              </button>
            ),
          )
        )}
      </div>
    </div>
  );
}

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={1.8}>
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
    </svg>
  );
}
