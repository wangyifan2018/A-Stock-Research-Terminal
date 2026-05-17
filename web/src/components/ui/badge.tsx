import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors",
  {
    variants: {
      variant: {
        default: "border-cyan-400/40 bg-cyan-400/10 text-cyan-200",
        success: "border-emerald-400/40 bg-emerald-400/10 text-emerald-200",
        warning: "border-amber-400/40 bg-amber-400/10 text-amber-200",
        danger: "border-rose-400/40 bg-rose-400/10 text-rose-200",
        muted: "border-slate-500/40 bg-slate-500/10 text-slate-300"
      }
    },
    defaultVariants: {
      variant: "default"
    }
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
