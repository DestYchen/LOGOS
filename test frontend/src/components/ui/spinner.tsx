import { cn } from "../../lib/utils";

type SpinnerProps = {
  className?: string;
  size?: "sm" | "md" | "lg";
};

const sizeMap: Record<NonNullable<SpinnerProps["size"]>, string> = {
  sm: "h-4 w-4 border-2",
  md: "h-6 w-6 border-2",
  lg: "h-8 w-8 border-[3px]",
};

export function Spinner({ className, size = "md" }: SpinnerProps) {
  return (
    <span
      className={cn(
        "inline-block animate-spin rounded-full border-primary border-t-transparent",
        sizeMap[size],
        className,
      )}
    />
  );
}
