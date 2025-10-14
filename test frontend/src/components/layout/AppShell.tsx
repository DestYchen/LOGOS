import { NavLink } from "react-router-dom";

import { cn } from "../../lib/utils";

type AppShellProps = {
  children: React.ReactNode;
};

const navLinkClasses =
  "inline-flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors hover:bg-muted hover:text-foreground";

function AppShell({ children }: AppShellProps) {
  return (
    <div className="min-h-screen bg-muted/20">
      <header className="border-b bg-background">
        <div className="container flex h-16 items-center justify-between">
          <span className="text-lg font-semibold tracking-tight text-primary">SupplyHub Console</span>
          <nav className="flex items-center gap-2">
            <NavLink
              to="/upload"
              className={({ isActive }) => cn(navLinkClasses, isActive && "bg-primary text-primary-foreground")}
            >
              Upload
            </NavLink>
            <NavLink
              to="/batches"
              className={({ isActive }) => cn(navLinkClasses, isActive && "bg-primary text-primary-foreground")}
            >
              Batches
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="container py-8">{children}</main>
    </div>
  );
}

export default AppShell;
