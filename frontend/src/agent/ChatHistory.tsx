import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ChatSummary } from "../api/types";
import { useApp } from "../store";
import { PlusCircleIcon, TrashIcon } from "../components/icons";

/** Past analyst conversations, listed in the left sidebar. Clicking one loads it
 *  into the chat panel; "New chat" starts a fresh thread. */
export function ChatHistory() {
  const { openChat, newChat, openChatId, chatsVersion, refreshChats } = useApp();
  const [chats, setChats] = useState<ChatSummary[]>([]);

  useEffect(() => {
    api
      .listChats()
      .then(setChats)
      .catch(() => setChats([]));
  }, [chatsVersion]);

  async function remove(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    await api.deleteChat(id).catch(() => {});
    if (id === openChatId) newChat();
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
      <div className="min-h-0 flex-1 space-y-0.5 overflow-auto">
        {chats.length === 0 ? (
          <p className="px-2 py-1 text-[11px] text-slate-400">No saved chats yet.</p>
        ) : (
          chats.map((c) => (
            <button
              key={c.id}
              onClick={() => openChat(c.id)}
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
                onClick={(e) => remove(e, c.id)}
                title="Delete chat"
                className="shrink-0 rounded p-0.5 text-slate-300 opacity-0 transition hover:text-red-500 group-hover:opacity-100"
              >
                <TrashIcon className="h-3.5 w-3.5" />
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
