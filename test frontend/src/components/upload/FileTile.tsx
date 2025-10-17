import { cn } from "../../lib/utils";
import { iconForExtension } from "./file-assets";

export type FileEntry = {
  id: string;
  name: string;
  size: number;
  error?: string;
  meta?: string;
};

type FileTileProps = {
  item: FileEntry;
  locked?: boolean;
  onRemove?: (id: string) => void;
};

export function FileTile({ item, locked, onRemove }: FileTileProps) {
  const ext = item.name.split(".").pop() ?? "";
  const icon = iconForExtension(ext);
  return (
    <div
      className={cn(
        "relative flex h-36 flex-col items-center justify-between rounded-2xl border border-primary/30 bg-primary/5 p-3 text-center shadow-sm transition-colors",
        locked && "opacity-80",
      )}
    >
      {!locked && onRemove ? (
        <button
          type="button"
          className="absolute right-2 top-2 rounded-full bg-background/80 p-1 text-xs text-muted-foreground shadow hover:text-foreground"
          onClick={() => onRemove(item.id)}
          aria-label="Удалить файл"
        >
          ×
        </button>
      ) : null}
      <img src={icon} alt="" className="h-14 w-14 rounded-xl bg-background/60 p-2 shadow" />
      <div className="min-h-[3rem] w-full overflow-hidden">
        <p className="truncate text-sm font-medium">{item.name}</p>
        <p className="text-xs text-muted-foreground">{item.meta ?? ""}</p>
      </div>
      {item.error ? <p className="text-xs text-destructive">{item.error}</p> : null}
    </div>
  );
}
