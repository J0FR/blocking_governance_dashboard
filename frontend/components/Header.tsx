"use client";

import { Loader2, RefreshCw } from "lucide-react";
import AppHeader from "./AppHeader";

export default function Header({
  onRefresh, refreshing,
}: {
  onRefresh: () => void;
  refreshing: boolean;
}) {
  return (
    <AppHeader>
      <nav className="hidden items-center gap-4 whitespace-nowrap 2xl:flex">
        <a className="hover:text-text" href="#summary">Summary</a>
        <a className="hover:text-text" href="#countries">Countries</a>
        <a className="hover:text-text" href="#cities">Cities</a>
        <a className="hover:text-text" href="#drivers">Drivers</a>
        <a className="hover:text-text" href="#profile">Who gets blocked</a>
      </nav>

      <button
        onClick={onRefresh} disabled={refreshing}
        className="flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-line bg-panel px-2.5 py-1.5 text-text hover:bg-panel2 disabled:opacity-60"
        title="Re-runs the query on Hive (can take several minutes)"
      >
        {refreshing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
        {refreshing ? "Refreshing…" : "Refresh data"}
      </button>
    </AppHeader>
  );
}
