import Link from "next/link";
import { Button } from "@/components/ui/button";

interface EmptyStateProps {
  icon: React.ElementType;
  title: string;
  description: string;
  action?: { label: string; href: string };
  secondary?: { label: string; href: string };
  children?: React.ReactNode;
}

export function EmptyState({ icon: Icon, title, description, action, secondary, children }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6">
      <div className="w-14 h-14 rounded-2xl bg-zinc-100 dark:bg-zinc-900 flex items-center justify-center mb-4">
        <Icon className="h-6 w-6 text-muted-foreground" />
      </div>
      <h3 className="text-lg font-semibold mb-1.5">{title}</h3>
      <p className="text-sm text-muted-foreground max-w-md leading-relaxed">{description}</p>
      {children && <div className="mt-5 w-full max-w-md">{children}</div>}
      {(action || secondary) && (
        <div className="mt-6 flex items-center gap-2">
          {action && (
            <Link href={action.href}>
              <Button size="sm">{action.label}</Button>
            </Link>
          )}
          {secondary && (
            <Link href={secondary.href}>
              <Button size="sm" variant="outline">{secondary.label}</Button>
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
