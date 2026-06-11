import { NavLink, useMatch, useNavigate } from "react-router-dom";
import clsx from "clsx";
import {
  LayoutDashboard,
  PlayCircle,
  GitCompare,
  FolderKanban,
  Clock,
  Workflow,
  LogOut,
} from "lucide-react";
import { useAuth } from "../contexts/AuthContext";

const linkBase =
  "flex items-center gap-2 px-3 py-2 rounded-md text-sm transition-colors";
const linkInactive =
  "text-text-muted hover:text-text-primary hover:bg-bg-hover";
const linkActive = "bg-bg-hover text-text-primary";

/**
 * Derives a display name and initials from the Supabase user object.
 *
 * Name source priority:
 *   1. user.user_metadata.name  — set during signUp({ options: { data: { name } } })
 *   2. user.email               — fallback when no name was provided
 *
 * Initials are the first 1-2 letters of the display name, uppercased.
 */
function getUserDisplay(user) {
  const name = user?.user_metadata?.name?.trim() || "";
  const email = user?.email || "";
  const displayName = name || email;

  // Build initials: "John Doe" → "JD", "shubham" → "S", "a@b.com" → "A"
  const initials =
    displayName
      .split(/[\s@]+/) // split on spaces or @ (handles email fallback)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0].toUpperCase())
      .join("") || "?";

  return { displayName, email, initials };
}

/**
 * Avatar circle showing the user's initials.
 * Matches the existing accent colour used for the "AI" logo badge.
 */
function Avatar({ initials }) {
  return (
    <div
      aria-hidden="true"
      className="w-8 h-8 rounded-full bg-accent/20 border border-accent/30 flex items-center justify-center shrink-0"
    >
      <span className="text-xs font-semibold text-accent leading-none">
        {initials}
      </span>
    </div>
  );
}

/**
 * Bottom-of-sidebar user profile block.
 * Shows avatar + name/email + a logout button row.
 */
function UserFooter({ user, onLogout }) {
  const { displayName, email, initials } = getUserDisplay(user);
  // Only show email separately when the display name is NOT the email itself
  const showEmail = displayName !== email;

  return (
    <div className="px-3 py-3 flex flex-col gap-1">
      {/* Identity row */}
      <div className="flex items-center gap-2.5 px-2 py-2 rounded-md">
        <Avatar initials={initials} />
        <div className="min-w-0 flex-1">
          <div
            className="text-sm font-medium text-text-primary leading-tight truncate"
            title={displayName}
          >
            {displayName}
          </div>
          {showEmail && (
            <div
              className="text-[11px] text-text-muted leading-tight truncate mt-0.5"
              title={email}
            >
              {email}
            </div>
          )}
        </div>
      </div>

      {/* Logout button */}
      <button
        onClick={onLogout}
        className={clsx(linkBase, linkInactive, "w-full text-left")}
      >
        <LogOut size={16} />
        Log out
      </button>
    </div>
  );
}

export function Sidebar() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  // Sidebar renders outside <Routes>, so useParams() won't see route params.
  // Match the project path directly off the current URL instead.
  const match = useMatch("/projects/:projectId/*");
  const projectId = match?.params?.projectId;
  const items = projectId
    ? [
        {
          to: `/projects/${projectId}/overview`,
          label: "Overview",
          icon: LayoutDashboard,
        },
        {
          to: `/projects/${projectId}/runs`,
          label: "Prompt Runs",
          icon: PlayCircle,
        },
        {
          to: `/projects/${projectId}/orchestration`,
          label: "Orchestration",
          icon: Workflow,
        },
        {
          to: `/projects/${projectId}/providers`,
          label: "Providers",
          icon: GitCompare,
        },
        { to: `/projects/${projectId}/history`, label: "History", icon: Clock },
      ]
    : [];

  const handleLogout = async () => {
    try {
      await signOut();
      navigate("/login", { replace: true });
    } catch (error) {
      console.error("Logout failed:", error);
      // MVP: console logging is sufficient.
      // When notifications/settings are added, surface auth errors via toast UI.
    }
  };

  return (
    <aside className="w-60 shrink-0 border-r border-border bg-bg-panel h-screen sticky top-0 flex flex-col">
      {/* ── Logo ── */}
      <div className="px-5 py-5 border-b border-border">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-accent flex items-center justify-center text-white text-xs font-bold">
            AI
          </div>
          <div>
            <div className="text-sm font-semibold leading-none">AI Tracker</div>
            <div className="text-[10px] text-text-muted mt-1">
              Search Visibility
            </div>
          </div>
        </div>
      </div>

      {/* ── Nav links ── */}
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

      {/* ── User profile footer ── */}
      <div className="border-t border-border">
        {user && <UserFooter user={user} onLogout={handleLogout} />}
        <div className="px-5 pb-3 text-[10px] text-text-dim">
          Phase 1 MVP · local
        </div>
      </div>
    </aside>
  );
}

export function Layout({ children }) {
  return (
    <div className="flex min-h-screen bg-bg">
      <Sidebar />
      <main className="flex-1 max-w-[1400px] mx-auto px-8 py-8">
        {children}
      </main>
    </div>
  );
}
