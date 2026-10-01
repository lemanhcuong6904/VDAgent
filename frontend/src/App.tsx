import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { ApiClient } from "./api/client";
import { ApiContext, useAgents, useTasks } from "./api/queries";
import { AgentList } from "./components/AgentList";
import { ChatPane } from "./components/chat/ChatPane";
import { Inspector } from "./components/inspector/Inspector";
import { TaskList } from "./components/TaskList";
import { UserPicker } from "./components/UserPicker";
import { useEventStream, type StreamState } from "./events/useEventStream";
import { UiProvider, useUi } from "./ui/UiContext";

const USER_KEY = "vdagent.userId";
const DEFAULT_AGENT = "orchestrator";

function storedUser(): string | null {
  try {
    return localStorage.getItem(USER_KEY);
  } catch {
    return null;
  }
}

/** One QueryClient (cache) and one ApiClient per selected user; switching users starts fresh. */
export function App() {
  const [userId, setUserId] = useState<string | null>(storedUser);
  const selectUser = useCallback((id: string | null) => {
    setUserId(id);
    try {
      if (id) localStorage.setItem(USER_KEY, id);
      else localStorage.removeItem(USER_KEY);
    } catch {
      // storage unavailable: selection just isn't persisted
    }
  }, []);

  const queryClient = useMemo(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 } },
      }),
    // A fresh cache per user: query keys carry no user id.
    [userId],
  );
  const api = useMemo(() => new ApiClient(userId), [userId]);

  return (
    <QueryClientProvider client={queryClient}>
      <ApiContext.Provider value={api}>
        <UiProvider key={userId ?? "none"}>
          <Shell userId={userId} onSelectUser={selectUser} />
        </UiProvider>
      </ApiContext.Provider>
    </QueryClientProvider>
  );
}

function Shell({ userId, onSelectUser }: { userId: string | null; onSelectUser: (id: string | null) => void }) {
  const stream = useEventStream(userId);
  const ui = useUi();
  return (
    <div className={`app${ui.sidebarOpen || ui.inspectorOpen ? " drawer-active" : ""}${ui.inspectorOpen ? "" : " inspector-hidden"}`}>
      <button className="drawer-backdrop" type="button" aria-label="Close open panel" onClick={ui.closePanels} />
      <aside className={`sidebar${ui.sidebarOpen ? " is-open" : ""}`} id="workspace-navigation">
        <div className="brand">vdagent</div>
        <button type="button" autoFocus={ui.sidebarOpen} className="icon-btn panel-close" onClick={ui.toggleSidebar} aria-label="Close navigation">
          Close
        </button>
        {userId && <SidebarLists />}
        <div className="sidebar-user">
          <UserPicker
            userId={userId}
            onSelect={onSelectUser}
            status={userId ? <StreamBadge state={stream} /> : null}
          />
        </div>
      </aside>
      {userId ? (
        <Workspace />
      ) : (
        <main className="main">
          <div className="chat-empty muted">Pick or create a user to start.</div>
        </main>
      )}
    </div>
  );
}

function useActiveTaskId(): string | null {
  const { taskId } = useUi();
  const tasks = useTasks();
  return taskId ?? tasks.data?.[0]?.id ?? null;
}

function SidebarLists() {
  const agents = useAgents();
  const ui = useUi();
  const activeTaskId = useActiveTaskId();
  return (
    <>
      <AgentList agents={agents.data} selected={ui.agent ?? DEFAULT_AGENT} error={agents.error} />
      <TaskList activeTaskId={activeTaskId} />
    </>
  );
}

function Workspace() {
  const agents = useAgents();
  const ui = useUi();
  const activeTaskId = useActiveTaskId();
  const name = ui.agent ?? DEFAULT_AGENT;
  const agent = agents.data?.find((a) => a.name === name) ?? agents.data?.[0];
  return (
    <>
      <main className="main">
        <header className="workspace-topbar">
          <button type="button" className="icon-btn mobile-control" aria-label="Open navigation" aria-expanded={ui.sidebarOpen} aria-controls="workspace-navigation" onClick={ui.toggleSidebar}>
            Menu
          </button>
          <div className="workspace-title">
            <span className="eyebrow">Analysis workspace</span>
            <strong>{agent?.name ?? "Loading agents"}</strong>
          </div>
          <button
            type="button"
            className="icon-btn inspector-toggle"
            aria-label={ui.inspectorOpen ? "Hide right sidebar" : "Show right sidebar"}
            title={ui.inspectorOpen ? "Hide right sidebar" : "Show right sidebar"}
            aria-expanded={ui.inspectorOpen}
            aria-controls="workspace-inspector"
            onClick={ui.toggleInspector}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="4" width="18" height="16" rx="2" />
              <path d="M15 4v16" />
              <path d={ui.inspectorOpen ? "m11 9 3 3-3 3" : "m13 9-3 3 3 3"} />
            </svg>
          </button>
        </header>
        {agents.isPending && (
          <section className="workspace-notice workspace-loading" aria-live="polite">
            <span className="notice-mark"><span className="spinner" /></span>
            <div>
              <span className="eyebrow">Connecting workspace</span>
              <h2>Loading available agents</h2>
              <p>Retrieving the team, their availability, and your recent work.</p>
            </div>
          </section>
        )}
        {agents.isError && (
          <section className="workspace-notice workspace-error" role="alert">
            <span className="notice-mark">!</span>
            <div>
              <span className="eyebrow">Connection problem</span>
              <h2>Agent service is unavailable</h2>
              <p>{agents.error.message}</p>
              <button type="button" className="btn" onClick={() => void agents.refetch()}>
                Try again
              </button>
            </div>
          </section>
        )}
        {agent ? (
          <ChatPane key={agent.name} agent={agent} taskId={ui.taskId} />
        ) : (
          <div className="chat-empty muted">{agents.isError ? agents.error.message : "Loading agents…"}</div>
        )}
      </main>
      <aside className={`inspector${ui.inspectorOpen ? " is-open" : ""}`} id="workspace-inspector">
        <div className="inspector-mobile-head">
          <span className="eyebrow">Inspector</span>
          <button type="button" autoFocus={ui.inspectorOpen} className="icon-btn panel-close" onClick={ui.toggleInspector} aria-label="Close inspector">
            Close
          </button>
        </div>
        <Inspector taskId={activeTaskId} />
      </aside>
    </>
  );
}

function StreamBadge({ state }: { state: StreamState }) {
  const label = { connecting: "connecting…", open: "live", reconnecting: "reconnecting…" }[state];
  return (
    <div className={`stream-badge stream-${state}`} title="Server-sent events connection">
      <span className="stream-dot" /> {label}
    </div>
  );
}
