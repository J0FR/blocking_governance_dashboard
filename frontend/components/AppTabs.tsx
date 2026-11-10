"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/", label: "Block calculator" },
  { href: "/impact", label: "Block impact & retention" },
];

export default function AppTabs() {
  const path = usePathname();
  return (
    <div className="flex shrink-0 rounded-lg border border-line bg-panel2 p-0.5 text-[13px]">
      {TABS.map((t) => {
        const active = t.href === "/" ? path === "/" : path.startsWith(t.href);
        return (
          <Link
            key={t.href} href={t.href}
            className={`whitespace-nowrap rounded-md px-3 py-1.5 font-medium ${active ? "bg-accent text-white" : "text-muted hover:text-text"}`}
          >
            {t.label}
          </Link>
        );
      })}
    </div>
  );
}
