import * as React from "react";

import { cn } from "../../lib/utils";

const alertVariants = {
  default: "border border-border bg-background text-foreground",
  info: "border border-primary/30 bg-primary/10 text-primary",
  success: "border border-emerald-500/30 bg-emerald-500/10 text-emerald-700",
  warning: "border border-amber-500/30 bg-amber-500/10 text-amber-700",
  destructive: "border border-destructive/30 bg-destructive/10 text-destructive",
};

export type AlertVariant = keyof typeof alertVariants;

export interface AlertProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: AlertVariant;
}

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(({ className, variant = "default", ...props }, ref) => (
  <div
    ref={ref}
    role="alert"
    className={cn("relative w-full rounded-lg px-4 py-3 text-sm", alertVariants[variant], className)}
    {...props}
  />
));
Alert.displayName = "Alert";

export { Alert };
