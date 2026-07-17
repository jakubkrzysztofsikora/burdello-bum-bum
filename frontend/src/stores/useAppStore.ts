import { create } from "zustand";

interface AppState {
  // UI State
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  currentView: string;
  setCurrentView: (v: string) => void;

  // Filters
  filters: {
    status: string[];
    provider: string[];
    dateFrom: string | null;
    dateTo: string | null;
  };
  setFilters: (filters: Partial<AppState["filters"]>) => void;
  clearFilters: () => void;

  // Search
  lastQuery: string;
  setLastQuery: (q: string) => void;

  // Task multi-select (project view batch actions)
  selectMode: boolean;
  setSelectMode: (on: boolean) => void;
  selectedTaskIds: Set<string>;
  toggleTaskSelected: (id: string) => void;
  setSelectedTasks: (ids: string[]) => void;
  clearSelectedTasks: () => void;
}

export const useAppStore = create<AppState>((set) => ({
  sidebarOpen: true,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  currentView: "dashboard",
  setCurrentView: (v) => set({ currentView: v }),

  filters: {
    status: [],
    provider: [],
    dateFrom: null,
    dateTo: null,
  },
  setFilters: (f) =>
    set((s) => ({ filters: { ...s.filters, ...f } })),
  clearFilters: () =>
    set({
      filters: { status: [], provider: [], dateFrom: null, dateTo: null },
    }),

  lastQuery: "",
  setLastQuery: (q) => set({ lastQuery: q }),

  selectMode: false,
  setSelectMode: (on) =>
    set(on ? { selectMode: true } : { selectMode: false, selectedTaskIds: new Set<string>() }),
  selectedTaskIds: new Set<string>(),
  toggleTaskSelected: (id) =>
    set((s) => {
      const next = new Set(s.selectedTaskIds);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { selectedTaskIds: next };
    }),
  setSelectedTasks: (ids) => set({ selectedTaskIds: new Set(ids) }),
  clearSelectedTasks: () =>
    set({ selectedTaskIds: new Set<string>() }),
}));
