import { useState } from 'react'
import { Check, MagnifyingGlass, PencilSimple, Plus, SidebarSimple, TrashSimple, X } from '@phosphor-icons/react'
import type { ChatSession } from '../lib/types'
import { groupSessions } from '../lib/sessionGroups'

export function Sidebar({
  sessions,
  activeSessionId,
  onSelect,
  onNew,
  onRename,
  onDelete,
  onCollapse,
}: {
  sessions: ChatSession[]
  activeSessionId: string
  onSelect: (id: string) => void
  onNew: () => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
  onCollapse?: () => void
}) {
  const [query, setQuery] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')

  const filtered = query.trim()
    ? sessions.filter((s) => s.title.toLowerCase().includes(query.trim().toLowerCase()))
    : sessions
  const groups = groupSessions(filtered)

  function startRename(s: ChatSession) {
    setEditingId(s.id)
    setDraftTitle(s.title)
  }

  function commitRename() {
    if (editingId && draftTitle.trim()) onRename(editingId, draftTitle.trim())
    setEditingId(null)
  }

  return (
    <div className="flex h-full w-full min-w-0 flex-col">
      <div className="flex shrink-0 flex-col gap-2.5 p-3">
        <div className="flex items-center gap-1.5">
          <button
            onClick={onNew}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-[10px] bg-ink px-3 py-2 text-sm font-medium text-paper transition-opacity hover:opacity-90 dark:bg-ink-dark dark:text-paper-dark"
          >
            <Plus size={15} weight="bold" />
            New chat
          </button>
          {onCollapse && (
            <button
              onClick={onCollapse}
              aria-label="Hide chat history"
              title="Hide chat history"
              className="hidden shrink-0 items-center justify-center rounded-[10px] p-2 text-ink-faint hover:bg-sunken hover:text-ink dark:text-ink-faint-dark dark:hover:bg-sunken-dark dark:hover:text-ink-dark md:flex"
            >
              <SidebarSimple size={16} />
            </button>
          )}
        </div>
        <div className="flex items-center gap-2 rounded-[10px] border border-line bg-surface px-2.5 py-1.5 focus-within:border-accent/50 dark:border-line-dark dark:bg-surface-dark dark:focus-within:border-accent-dark/50">
          <MagnifyingGlass size={14} className="text-ink-faint dark:text-ink-faint-dark" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
            className="w-full bg-transparent text-sm text-ink placeholder:text-ink-faint focus:outline-none dark:text-ink-dark dark:placeholder:text-ink-faint-dark"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden px-2 pb-3">
        {groups.length === 0 && (
          <p className="px-2.5 py-4 text-center text-xs text-ink-faint dark:text-ink-faint-dark">No chats match "{query}".</p>
        )}
        {groups.map((group) => (
          <div key={group.label} className="mb-1">
            <h3 className="px-2.5 pb-1.5 pt-3 text-[11px] font-medium uppercase tracking-wide text-ink-faint dark:text-ink-faint-dark">
              {group.label}
            </h3>
            <div className="space-y-0.5">
              {group.sessions.map((s) => {
                const isActive = s.id === activeSessionId
                const isEditing = editingId === s.id
                return (
                  <div
                    key={s.id}
                    className={`group flex items-center gap-1.5 rounded-[10px] px-2.5 py-2 text-sm ${
                      isActive
                        ? 'bg-accent-soft text-accent-strong dark:bg-accent-soft-dark dark:text-accent-dark'
                        : 'text-ink-muted hover:bg-sunken dark:text-ink-muted-dark dark:hover:bg-sunken-dark'
                    }`}
                  >
                    {isEditing ? (
                      <div className="flex flex-1 items-center gap-1">
                        <input
                          autoFocus
                          value={draftTitle}
                          onChange={(e) => setDraftTitle(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') commitRename()
                            if (e.key === 'Escape') setEditingId(null)
                          }}
                          className="w-full rounded-[6px] border border-accent/40 bg-surface px-1.5 py-0.5 text-sm text-ink focus:outline-none dark:border-accent-dark/40 dark:bg-surface-dark dark:text-ink-dark"
                        />
                        <button onClick={commitRename} className="shrink-0 text-accent dark:text-accent-dark">
                          <Check size={14} weight="bold" />
                        </button>
                        <button onClick={() => setEditingId(null)} className="shrink-0 text-ink-faint dark:text-ink-faint-dark">
                          <X size={14} weight="bold" />
                        </button>
                      </div>
                    ) : (
                      <>
                        <button onClick={() => onSelect(s.id)} className="min-w-0 flex-1 truncate text-left">
                          {s.title || 'New chat'}
                        </button>
                        <div className="hidden shrink-0 items-center gap-0.5 group-hover:flex">
                          <button
                            onClick={() => startRename(s)}
                            aria-label="Rename chat"
                            className="rounded-[6px] p-1 text-ink-faint hover:text-ink dark:text-ink-faint-dark dark:hover:text-ink-dark"
                          >
                            <PencilSimple size={13} />
                          </button>
                          <button
                            onClick={() => onDelete(s.id)}
                            aria-label="Delete chat"
                            className="rounded-[6px] p-1 text-ink-faint hover:text-brick dark:text-ink-faint-dark dark:hover:text-brick-dark"
                          >
                            <TrashSimple size={13} />
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
