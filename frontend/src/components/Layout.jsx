import { NavLink, useMatch } from "react-router-dom";
import clsx from "clsx";
import {
  LayoutDashboard,
  PlayCircle,
  Users,
  GitCompare,
  FolderKanban,
  Clock,
  Workflow,
} from "lucide-react";

const linkBase =
  "flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors";
const linkInactive = "text-text-muted hover:text-text-primary hover:bg-bg-hover";
const linkActive = "bg-bg-hover text-text-primary";

export function Sidebar() {
  // Sidebar renders outside <Routes>, so useParams() won't see route params.
  // Match the project path directly off the current URL instead.
  const match = useMatch("/projects/:projectId/*");
  const projectId = match?.params?.projectId;
  const items = projectId
    ? [
        { to: `/projects/${projectId}/overview`, label: "Overview", icon: LayoutDashboard },
        { to: `/projects/${projectId}/runs`, label: "Prompt Runs", icon: PlayCircle },
        { to: `/projects/${projectId}/orchestration`, label: "Orchestration", icon: Workflow },
        { to: `/projects/${projectId}/competitors`, label: "Competitors", icon: Users },
        { to: `/projects/${projectId}/providers`, label: "Providers", icon: GitCompare },
        { to: `/projects/${projectId}/history`, label: "History", icon: Clock },
      ]
    : [];

  return (
    <aside className="w-60 shrink-0 border-r border-border bg-bg-panel h-screen sticky top-0 flex flex-col">
      <div className="px-5 py-5 border-b border-border">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-accent flex items-center justify-center text-white text-xs font-bold">
            AI
          </div>
          <div>
            <div className="text-sm font-semibold leading-none">AI Tracker</div>
            <div className="text-[10px] text-text-muted mt-1">Search Visibility</div>
          </div>
        </div>
      </div>

      <nav className="p-3 flex flex-col gap-0.5 flex-1">
        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            clsx(linkBase, isActive ? linkActive : linkInactive)
          }
        >
          <FolderKanban size={16} /> Projects
        </NavLink>
        {items.length > 0 && (
          <>
            <div className="mt-4 mb-2 px-3 text-[10px] uppercase tracking-wider text-text-dim">
              Project
            </div>
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  clsx(linkBase, isActive ? linkActive : linkInactive)
                }
              >
                <item.icon size={16} />
                {item.label}
              </NavLink>
            ))}
          </>
        )}
      </nav>

      <div className="px-5 py-3 text-[10px] text-text-dim border-t border-border">
        Phase 1 MVP · local
      </div>
    </aside>
  );
}

export function Layout({ children }) {
  return (
    <div className="flex min-h-screen bg-bg">
      <Sidebar />
      <main className="flex-1 max-w-[1400px] mx-auto px-8 py-8">{children}</main>
    </div>
  );
}
