import { createContext, useContext, useMemo, useReducer, type ReactNode } from "react";

export type InspectorTab = "task" | "artifact";

export interface UiState {
  /** Agent whose chat is shown; null → default (orchestrator). */
  agent: string | null;
  /** Selected task shown in the Inspector and chat. */
  taskId: string | null;
  tab: InspectorTab;
  artifactId: string | null;
  /** Recently opened artifacts, most recent first. */
  recentArtifacts: string[];
  /** Whether the inspector is open; initialized from the current viewport. */
  sidebarOpen: boolean;
  inspectorOpen: boolean;
}

export interface Ui extends UiState {
  selectAgent: (agent: string) => void;
  selectTask: (taskId: string, agent: string) => void;
  openArtifact: (artifactId: string) => void;
  setTab: (tab: InspectorTab) => void;
  toggleSidebar: () => void;
  toggleInspector: () => void;
  closePanels: () => void;
}

type Action =
  | { type: "agent"; agent: string }
  | { type: "task"; taskId: string; agent: string }
  | { type: "artifact"; artifactId: string }
  | { type: "tab"; tab: InspectorTab }
  | { type: "sidebar" }
  | { type: "inspector" }
  | { type: "closePanels" };

const RECENT_LIMIT = 8;

export function uiReducer(state: UiState, action: Action): UiState {
  switch (action.type) {
    case "agent":
      return { ...state, agent: action.agent, taskId: null, sidebarOpen: false };
    case "task":
      return { ...state, agent: action.agent, taskId: action.taskId, tab: "task", sidebarOpen: false, inspectorOpen: true };
    case "artifact":
      return {
        ...state,
        artifactId: action.artifactId,
        tab: "artifact",
        inspectorOpen: true,
        recentArtifacts: [
          action.artifactId,
          ...state.recentArtifacts.filter((id) => id !== action.artifactId),
        ].slice(0, RECENT_LIMIT),
      };
    case "tab":
      return { ...state, tab: action.tab };
    case "sidebar":
      return { ...state, sidebarOpen: !state.sidebarOpen };
    case "inspector":
      return { ...state, inspectorOpen: !state.inspectorOpen };
    case "closePanels":
      return { ...state, sidebarOpen: false, inspectorOpen: false };
  }
}

export const initialUiState: UiState = {
  agent: null,
  taskId: null,
  tab: "task",
  artifactId: null,
  recentArtifacts: [],
  sidebarOpen: false,
  inspectorOpen: false,
};

const UiContext = createContext<Ui | null>(null);

export function UiProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(uiReducer, initialUiState, (initialState) => ({
    ...initialState,
    inspectorOpen:
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(min-width: 1121px)").matches,
  }));
  const value = useMemo<Ui>(
    () => ({
      ...state,
      selectAgent: (agent) => dispatch({ type: "agent", agent }),
      selectTask: (taskId, agent) => dispatch({ type: "task", taskId, agent }),
      openArtifact: (artifactId) => dispatch({ type: "artifact", artifactId }),
      setTab: (tab) => dispatch({ type: "tab", tab }),
      toggleSidebar: () => dispatch({ type: "sidebar" }),
      toggleInspector: () => dispatch({ type: "inspector" }),
      closePanels: () => dispatch({ type: "closePanels" }),
    }),
    [state],
  );
  return <UiContext.Provider value={value}>{children}</UiContext.Provider>;
}

export function useUi(): Ui {
  const ui = useContext(UiContext);
  if (!ui) throw new Error("useUi must be used inside <UiProvider>");
  return ui;
}
