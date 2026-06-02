import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  FolderKanban,
  CheckSquare,
  Layers,
  FileText,
  Search,
  Upload,
  Settings,
} from "lucide-react";
import { useAppStore } from "../stores/useAppStore";

const LINKS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/tasks", label: "Tasks", icon: CheckSquare },
  { to: "/artifacts", label: "Artifacts", icon: Layers },
  { to: "/transcripts", label: "Transcripts", icon: FileText },
  { to: "/search", label: "Search", icon: Search },
  { to: "/todoist", label: "Todoist Export", icon: Upload },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const { sidebarOpen, toggleSidebar } = useAppStore();

  return (
    <aside
      className={`fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-bb-border bg-bb-card transition-transform duration-200 ${
        sidebarOpen ? "translate-x-0" : "-translate-x-full"
      } w-56 lg:translate-x-0`}
    >
      <div className="flex items-center justify-between border-b border-bb-border px-4 py-3">
        <span className="text-sm font-bold tracking-tight">BB Dashboard</span>
        <button
          onClick={toggleSidebar}
          className="rounded p-1 text-bb-muted hover:bg-bb-border hover:text-bb-text lg:hidden"
        >
          ✕
        </button>
      </div>

      <nav className="flex-1 space-y-1 p-3">
        {LINKS.map((l) => {
          const Icon = l.icon;
          return (
            <NavLink
              key={l.to}
              to={l.to}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-md px-3 py-2 text-sm transition ${
                  isActive
                    ? "bg-bb-accent/20 text-bb-accent font-medium"
                    : "text-bb-muted hover:bg-bb-border hover:text-bb-text"
                }`
              }
              end={l.to === "/"}
            >
              <Icon size={16} />
              {l.label}
            </NavLink>
          );
        })}
      </nav>

      <div className="border-t border-bb-border p-3 text-xs text-bb-muted">
        Burdello Bum-Bum v0.1
      </div>
    </aside>
  );
}
