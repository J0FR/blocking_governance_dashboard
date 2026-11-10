"use client";

import { ArrowDown, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { GeoRow } from "@/lib/api";
import { compact, moneyCompact, pct } from "@/lib/format";
import { Absorption, KindDots } from "./ui";

type SortKey = "lost_net" | "lost_gmv" | "lost_gmv_week" | "lost_trips_week" | "market_share_lost" | "coverage" | "blocked_drivers";

const PAGE = 25;

export default function GeoTable<T extends GeoRow>({
  rows, label, plural, nameOf, subOf, keyOf, horizon, selectedKey, onSelect, searchable = false, maxHeight = 520,
}: {
  rows: T[];
  label: string;
  plural?: string;
  nameOf: (r: T) => string;
  subOf?: (r: T) => string; // secondary text (e.g. city id), also searchable
  keyOf: (r: T) => string;
  horizon: number;
  selectedKey?: string | null;
  onSelect?: (r: T) => void;
  searchable?: boolean;
  maxHeight?: number | null; // null = grow with the content (no vertical scroll)
}) {
  const [sort, setSort] = useState<SortKey>("lost_net");
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(PAGE);

  const sorted = useMemo(() => {
    const val = (r: T) => {
      const v = r[sort];
      return v == null ? Infinity : (v as number);
    };
    const needle = q.trim().toLowerCase();
    const base = needle
      ? rows.filter((r) => nameOf(r).toLowerCase().includes(needle) || (subOf?.(r) ?? "").toLowerCase().includes(needle))
      : rows;
    // lower coverage = more critical, so ascending; everything else descending
    return [...base].sort((a, b) => (sort === "coverage" ? val(a) - val(b) : val(b) - val(a)));
  }, [rows, sort, q, nameOf, subOf]);

  const visible = searchable ? sorted.slice(0, shown) : sorted;

  // plain render helper (not a component) so header cells keep their identity between renders
  const h = (k: SortKey | undefined, className: string, children: React.ReactNode) => (
    <th className={`th px-3 py-2 ${className}`}>
      {k ? (
        <button onClick={() => setSort(k)} className="inline-flex items-center gap-1 uppercase hover:text-text">
          {children}
          {sort === k && <ArrowDown size={11} />}
        </button>
      ) : children}
    </th>
  );

  return (
    <div className="card overflow-hidden">
      {searchable && (
        <div className="flex items-center gap-2 border-b border-line bg-panel2 p-2.5">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-2 text-muted" />
            <input
              value={q} onChange={(e) => { setQ(e.target.value); setShown(PAGE); }}
              placeholder={`Search ${label.toLowerCase()} name or ID`}
              className="w-56 rounded-md border border-line bg-panel py-1.5 pl-8 pr-2 text-[13px]"
            />
          </div>
          <span className="text-[12px] text-muted">
            {sorted.length.toLocaleString("en-US")} {sorted.length === 1 ? label.toLowerCase() : (plural ?? label.toLowerCase() + "s")}
          </span>
        </div>
      )}
      <div className="overflow-auto" style={maxHeight == null ? undefined : { maxHeight }}>
        <table className="w-full min-w-[1080px] border-collapse text-[13px]">
          <thead className="sticky top-0 z-10 bg-panel2">
            <tr className="border-b border-line">
              <th rowSpan={2} className="th px-3 py-2 text-left align-bottom">{label}</th>
              {h("blocked_drivers", "text-right",
                <>Blocked<br /><span className="font-normal normal-case">temp / perm</span></>)}
              <th colSpan={3} className="th border-l border-line px-3 pt-2 text-center">Short term &middot; per week</th>
              <th colSpan={4} className="th border-l border-line px-3 pt-2 text-center">Over {horizon} days</th>
              {h("market_share_lost", "border-l border-line text-right", <>% of trips</>)}
              {h("coverage", "border-l border-line text-left", <>Absorption</>)}
            </tr>
            <tr className="border-b border-line">
              <th />
              {h("lost_trips_week", "border-l border-line text-right", "Trips")}
              {h(undefined, "text-right", "TSH")}
              {h("lost_gmv_week", "text-right", "GMV")}
              {h(undefined, "border-l border-line text-right", "Trips")}
              {h(undefined, "text-right", "TSH")}
              {h("lost_gmv", "text-right", "GMV")}
              {h("lost_net", "text-right", "Economic loss")}
              <th className="border-l border-line" />
              <th className="border-l border-line" />
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => {
              const k = keyOf(r);
              const active = selectedKey === k;
              return (
                <tr
                  key={k}
                  onClick={() => onSelect?.(r)}
                  className={`tnum border-b border-line/70 ${onSelect ? "cursor-pointer hover:bg-accentsoft/60" : ""} ${active ? "bg-accentsoft" : ""} ${r.status === "none" ? "text-muted" : ""}`}
                >
                  <td className="px-3 py-1.5 font-medium">
                    {nameOf(r)}
                    {subOf && <span className="ml-1.5 font-mono text-[11px] font-normal text-muted">{subOf(r)}</span>}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    {r.blocked_drivers > 0 ? (
                      <>
                        <b>{r.blocked_drivers.toLocaleString("en-US")}</b>{" "}
                        <KindDots temporary={r.blocked_temporary} permanent={r.blocked_permanent} />
                      </>
                    ) : "–"}
                  </td>
                  <td className="border-l border-line px-3 py-1.5 text-right">{compact(r.lost_trips_week)}</td>
                  <td className="px-3 py-1.5 text-right">{compact(r.lost_tsh_week)}</td>
                  <td className="px-3 py-1.5 text-right">{moneyCompact(r.lost_gmv_week)}</td>
                  <td className="border-l border-line px-3 py-1.5 text-right">{compact(r.lost_trips)}</td>
                  <td className="px-3 py-1.5 text-right">{compact(r.lost_tsh)}</td>
                  <td className="px-3 py-1.5 text-right">{moneyCompact(r.lost_gmv)}</td>
                  <td className="px-3 py-1.5 text-right font-semibold">{moneyCompact(r.lost_net)}</td>
                  <td className="border-l border-line px-3 py-1.5 text-right">{r.lost_trips_week > 0 ? pct(r.market_share_lost, 4) : "–"}</td>
                  <td className="border-l border-line px-3 py-1.5">
                    <Absorption lost={r.lost_trips_week} capacity={r.capacity_trips_week} />
                  </td>
                </tr>
              );
            })}
            {!visible.length && (
              <tr><td colSpan={11} className="px-3 py-8 text-center text-muted">No rows</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {searchable && sorted.length > visible.length && (
        <div className="border-t border-line bg-panel2 px-3 py-2 text-center">
          <button onClick={() => setShown((s) => s + PAGE * 4)} className="text-[13px] font-medium text-accent hover:underline">
            Show more ({(sorted.length - visible.length).toLocaleString("en-US")} remaining)
          </button>
        </div>
      )}
      <p className="border-t border-line bg-panel2 px-3 py-2 text-[12px] text-muted">
        Absorption: the trips per week the blocked drivers stop doing vs. the spare capacity of the drivers who stay active.
        &ldquo;Absorbed&rdquo; = the remaining drivers can cover all of it; otherwise it shows how many trips per week they can cover.
        Economic loss = GMV &minus; CX cost avoided (compensations + tickets &times; $0.69).
      </p>
    </div>
  );
}
