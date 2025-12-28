import { useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ChevronLeft, History, Upload, type LucideIcon } from "lucide-react";

import logomark from "../../assets/logo.png";
import { useHistoryContext } from "../../contexts/history-context";
import { cn, deriveHistoryRoute, mapBatchStatus, statusLabel, type StatusKey } from "../../lib/utils";
import { formatPacketTimestamp } from "../../lib/packet";
import { Button } from "../ui/button";
import { Spinner } from "../ui/spinner";

type AppShellProps = {
  children: React.ReactNode;
};

type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
};

const NAV_ITEMS: NavItem[] = [
  { to: "/new", label: "Новый пакет", icon: Upload },
  { to: "/history", label: "История", icon: History },
];

function formatCompactStamp(value: string | null | undefined) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) {
    return "--";
  }

  const now = new Date();
  const isToday =
    date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();

  const options: Intl.DateTimeFormatOptions = isToday
    ? { hour: "2-digit", minute: "2-digit", hour12: false }
    : { day: "2-digit", month: "2-digit" };

  return new Intl.DateTimeFormat("ru-RU", options).format(date);
}

function AppShell({ children }: AppShellProps) {
  const location = useLocation();
  const { batches, loading, error, recentBatchId } = useHistoryContext();
  const [isCollapsed, setIsCollapsed] = useState(false);

  const isDenseLayoutPage = location.pathname.startsWith("/table/") || location.pathname.startsWith("/resolve/");
  const contentWrapperClassName = cn(
    "mx-auto w-full",
    isDenseLayoutPage ? (isCollapsed ? "max-w-none" : "max-w-[120rem]") : "max-w-7xl",
    isDenseLayoutPage
      ? isCollapsed
        ? "px-2 py-4 lg:px-3 lg:py-5"
        : "px-3 py-5 lg:px-4 lg:py-6"
      : "px-6 py-10 lg:px-12 lg:py-12",
  );

  const orderedBatches = useMemo(() => {
    return [...batches].sort((a, b) => {
      const aDate = a.created_at ? new Date(a.created_at).getTime() : 0;
      const bDate = b.created_at ? new Date(b.created_at).getTime() : 0;
      return bDate - aDate;
    });
  }, [batches]);

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside
        className={cn(
          "hidden shrink-0 border-r bg-muted/30 transition-[width] duration-300 ease-out lg:flex",
          isCollapsed ? "w-[96px]" : "w-[320px]",
        )}
      >
        <div className="flex h-screen w-full flex-col">
          <div className={cn("border-b", isCollapsed ? "px-3 py-4" : "px-6 pb-5 pt-6")}>
            <div className={cn("flex items-center", isCollapsed ? "flex-col gap-3" : "justify-between")}>
              <Link to="/new" className="inline-flex items-center justify-center gap-3">
                <img
                  src={logomark}
                  alt="Логос"
                  className={cn(
                    "max-w-full object-contain transition-all",
                    isCollapsed ? "h-auto w-12" : "h-5 w-auto",
                  )}
                />
              </Link>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                aria-label={isCollapsed ? "Развернуть меню" : "Свернуть меню"}
                aria-pressed={isCollapsed}
                className="h-10 w-10 rounded-xl"
                onClick={() => setIsCollapsed((prev) => !prev)}
              >
                <ChevronLeft className={cn("h-4 w-4 transition-transform duration-300", isCollapsed && "rotate-180")} />
              </Button>
            </div>
          </div>

          <nav className={cn("flex flex-col gap-2 py-4", isCollapsed ? "items-center px-2" : "px-4")}>
            {NAV_ITEMS.map((item) => {
              const isActive = location.pathname === item.to || location.pathname.startsWith(`${item.to}/`);
              const Icon = item.icon;
              return (
                <Button
                  key={item.to}
                  asChild
                  size={isCollapsed ? "icon" : "lg"}
                  variant={isActive ? "default" : "secondary"}
                  className={cn(
                    isCollapsed ? "h-11 w-11" : "h-11 w-full justify-start gap-3 px-4",
                    isActive ? "shadow-sm" : "bg-muted text-foreground hover:bg-muted/80",
                  )}
                >
                  <Link to={item.to} aria-label={item.label} title={item.label} aria-current={isActive ? "page" : undefined}>
                    <Icon className="h-5 w-5 shrink-0" />
                    {isCollapsed ? <span className="sr-only">{item.label}</span> : <span className="truncate">{item.label}</span>}
                  </Link>
                </Button>
              );
            })}
          </nav>

          <div className={cn("px-4", isCollapsed && "px-0 text-center")}>
            <h2
              className={cn(
                "text-xs font-semibold uppercase tracking-wide text-muted-foreground",
                isCollapsed && "sr-only",
              )}
            >
              История пакетов
            </h2>
          </div>

          <div className={cn("mt-2 flex-1 overflow-y-auto pb-6", isCollapsed ? "px-2" : "px-3")}>
            {loading ? (
              <div
                className={cn(
                  "flex items-center justify-center py-6 text-muted-foreground",
                  isCollapsed ? "flex-col gap-2 text-xs" : "gap-3 text-sm",
                )}
              >
                <Spinner size="sm" />
                <span className={cn(isCollapsed && "sr-only")}>Загрузка истории...</span>
              </div>
            ) : error ? (
              <div
                className={cn(
                  "rounded-md border border-destructive/40 bg-destructive/10 px-3 py-3 text-sm text-destructive",
                  isCollapsed && "px-2 text-center text-xs",
                )}
              >
                Не удалось загрузить историю: {error.message}
              </div>
            ) : orderedBatches.length === 0 ? (
              <p className={cn("px-2 py-4 text-sm text-muted-foreground", isCollapsed && "text-center text-xs")}>
                История пуста. Загрузите первый пакет.
              </p>
            ) : (
              <ul className={cn("flex flex-col gap-2", isCollapsed ? "items-center" : "items-stretch")}>
                {orderedBatches.map((batch) => {
                  const mappedStatus: StatusKey = mapBatchStatus(batch.status);
                  const target = deriveHistoryRoute(batch.id, mappedStatus);
                  const isActive = location.pathname.includes(batch.id) || recentBatchId === batch.id;
                  const compactStamp = formatCompactStamp(batch.created_at);
                  const fullDate = formatPacketTimestamp(batch.created_at);
                  const statusText = statusLabel(mappedStatus);
                  return (
                    <li key={batch.id}>
                      <Link
                        to={target}
                        aria-label={`Пакет ${fullDate}. Статус: ${statusText}`}
                        title={`${fullDate} - ${statusText}`}
                        className={cn(
                          isCollapsed
                            ? "group flex h-12 w-12 items-center justify-center rounded-lg border border-transparent bg-background/70 text-[11px] font-semibold leading-tight text-foreground transition-colors hover:border-primary/40 hover:bg-primary/5"
                            : "group flex h-11 w-full items-center justify-start rounded-xl border border-transparent bg-background/70 px-3 text-sm font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-primary/5",
                          isActive && "border-primary/60 bg-primary/10 text-primary",
                        )}
                      >
                        <span className={cn("text-center", !isCollapsed && "truncate")}>
                          {isCollapsed ? compactStamp : fullDate}
                        </span>
                        <span className="sr-only">{statusText}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto bg-muted/20">
        <div className={contentWrapperClassName}>{children}</div>
      </main>
    </div>
  );
}

export default AppShell;
