import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/format";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-control px-2.5 py-1 text-xs font-medium",
  {
    variants: {
      variant: {
        neutral: "bg-line/40 text-ink-muted",
        pass: "bg-pass/10 text-pass",
        warn: "bg-warn/10 text-warn",
        alert: "bg-alert/10 text-alert",
        cobalt: "bg-cobalt-soft text-cobalt",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />;
}

export { Badge, badgeVariants };
