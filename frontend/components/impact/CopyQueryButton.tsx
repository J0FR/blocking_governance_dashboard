"use client";

import { Check, Copy, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { impactApi, type QueryKind } from "@/lib/api";

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // older browsers / insecure context: select-and-copy fallback
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;opacity:0;pointer-events:none";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
    return ok;
  }
}

/** Copies the query to run, with the date window of today already applied. */
export default function CopyQueryButton({ kind }: { kind: QueryKind }) {
  const [state, setState] = useState<"idle" | "busy" | "copied" | "failed">("idle");
  const [dates, setDates] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const onClick = async () => {
    setState("busy");
    let next: "copied" | "failed" = "failed";
    try {
      const q = await impactApi.query(kind);
      if (await copyText(q.sql)) {
        next = "copied";
        setDates(`${q.dates.start_date} → ${q.dates.end_date}`);
      }
    } catch {
      next = "failed";
    }
    setState(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 3500);
  };

  return (
    <button onClick={onClick} disabled={state === "busy"}
      className="flex items-center gap-1.5 rounded-md border border-line bg-panel px-2 py-0.5 font-medium text-text hover:bg-panel2 disabled:opacity-60"
      title="Copies the SQL with the real dates already in it (no parameters), to run it on your side">
      {state === "busy" ? <Loader2 size={13} className="animate-spin" /> : state === "copied" ? <Check size={13} className="text-ok" /> : <Copy size={13} />}
      {state === "copied" ? `Copied · ${dates}` : state === "failed" ? "Could not copy" : "Copy query"}
    </button>
  );
}
