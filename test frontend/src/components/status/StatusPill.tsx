import { Badge } from "../ui/badge";
import { statusLabel, statusVariant, type StatusKey } from "../../lib/utils";

type StatusPillProps = {
  status: StatusKey;
  className?: string;
};

export function StatusPill({ status, className }: StatusPillProps) {
  return (
    <Badge variant={statusVariant(status)} className={className}>
      {statusLabel(status)}
    </Badge>
  );
}
