import type { ReactNode } from "react";
import AppTabs from "./AppTabs";

/**
 * One header for every page. Brand + tabs are always in the same spot (fixed height, fixed order),
 * so switching sections never moves them; only the controls on the right change per page.
 */
export default function AppHeader({ children }: { children?: ReactNode }) {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-panel">
      <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-4 px-5">
        <span className="shrink-0 text-[15px] font-semibold">Block support</span>
        <AppTabs />
        <div className="ml-auto flex min-w-0 items-center gap-x-5 overflow-hidden text-[13px] text-muted">{children}</div>
      </div>
    </header>
  );
}

export function PageTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div>
      <h1 className="text-xl font-semibold leading-tight">{title}</h1>
      <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>
    </div>
  );
}
