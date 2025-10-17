import { useMemo } from "react";
import { Link, useLocation } from "react-router-dom";

import logomark from "../../assets/logo.png";
import { useHistoryContext } from "../../contexts/history-context";
import { cn, deriveHistoryRoute, formatShortDate, mapBatchStatus, type StatusKey } from "../../lib/utils";
import { formatPacketTimestamp } from "../../lib/packet";
import { Button } from "../ui/button";
import { Spinner } from "../ui/spinner";
import { StatusPill } from "../status/StatusPill";

type AppShellProps = {
  children: React.ReactNode;
};

const NAV_ITEMS = [
  { to: "/new", label: "Новый пакет" },
  { to: "/history", label: "История" },
];

function AppShell({ children }: AppShellProps) {
  const location = useLocation();
  const { batches, loading, error, recentBatchId } = useHistoryContext();

  const orderedBatches = useMemo(() => {
    return [...batches].sort((a, b) => {
      const aDate = a.created_at ? new Date(a.created_at).getTime() : 0;
      const bDate = b.created_at ? new Date(b.created_at).getTime() : 0;
      return bDate - aDate;
    });
  }, [batches]);

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="hidden w-[320px] shrink-0 border-r bg-muted/30 lg:flex">
        <div className="flex h-screen w-full flex-col">
          <div className="border-b px-6 pb-5 pt-6">
            <Link to="/new" className="inline-flex items-center gap-3">
              <img src={logomark} alt="Логос" className="h-5 w-auto" />
            </Link>
          </div>

          <nav className="flex flex-col gap-2 px-4 py-4">
            {NAV_ITEMS.map((item) => {
              const isActive = location.pathname === item.to || location.pathname.startsWith(`${item.to}/`);
              return (
                <Button
                  key={item.to}
                  asChild
                  variant={isActive ? "default" : "secondary"}
                  className={cn(
                    "justify-start gap-2",
                    isActive ? "shadow-sm" : "bg-muted text-foreground hover:bg-muted/80",
                  )}
                >
                  <Link to={item.to}>{item.label}</Link>
                </Button>
              );
            })}
          </nav>

          <div className="px-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">История пакетов</h2>
          </div>

          <div className="mt-2 flex-1 overflow-y-auto px-2 pb-6">
            {loading ? (
              <div className="flex items-center justify-center py-6 text-muted-foreground">
                <Spinner className="mr-3" size="sm" /> Загрузка истории...
              </div>
            ) : error ? (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-3 text-sm text-destructive">
                Не удалось загрузить историю: {error.message}
              </div>
            ) : orderedBatches.length === 0 ? (
              <p className="px-2 py-4 text-sm text-muted-foreground">История пуста. Загрузите первый пакет.</p>
            ) : (
              <ul className="space-y-2">
                {orderedBatches.map((batch) => {
                  const mappedStatus: StatusKey = mapBatchStatus(batch.status);
                  const target = deriveHistoryRoute(batch.id, mappedStatus);
                  const isActive = location.pathname.includes(batch.id) || recentBatchId === batch.id;
                  return (
                    <li key={batch.id}>
                      <Link
                        to={target}
                        className={cn(
                          "group block rounded-xl border border-transparent bg-background/60 px-3 py-3 transition-colors hover:border-primary/40 hover:bg-primary/5",
                          isActive && "border-primary/60 bg-primary/10",
                        )}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium" title={batch.id}>
                              Пакет {formatPacketTimestamp(batch.created_at)}
                            </p>
                            <p className="truncate text-xs text-muted-foreground">{formatShortDate(batch.created_at)}</p>
                          </div>
                          <StatusPill status={mappedStatus} />
                        </div>
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
        <div className="mx-auto w-full max-w-7xl px-6 py-10 lg:px-12 lg:py-12">{children}</div>
      </main>
    </div>
  );
}

export default AppShell;
