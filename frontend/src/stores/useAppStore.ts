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
}));
