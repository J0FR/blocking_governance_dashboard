"use client";

import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { DriverQuery, DriverRow } from "@/lib/api";
import { api } from "@/lib/api";
import { compact, dec, int, KIND_COLOR, KIND_LABEL, moneyCompact } from "@/lib/format";

export default function DriversTable({
  q, setQ, data, loading, focusLabel, onClearFocus, horizon,
}: {
  q: DriverQuery;
  setQ: (p: Partial<DriverQuery>) => void;
  data: { total: number; rows: DriverRow[] } | undefined;
  loading: boolean;
  focusLabel: string | null;
  onClearFocus: () => void;
  horizon: number;
}) {
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / q.page_size));

  // Debounce typing: with 100k drivers every keystroke would otherwise hit the server.
  const [text, setText] = useState(q.search);
  useEffect(() => {
    if (text === q.search) return;
    const t = setTimeout(() => setQ({ search: text, page: 0 }), 350);
    return () => clearTimeout(t);
  }, [text, q.search, setQ]);

  const sortBy = (key: string) =>
    setQ({ sort_by: key, sort_dir: q.sort_by === key && q.sort_dir === "desc" ? "asc" : "desc", page: 0 });

  // plain render helper (not a component) so header cells keep their identity between renders
  const h = (key: string | null, className: string, children: React.ReactNode, extra: { rowSpan?: number } = {}) => (
    <th rowSpan={extra.rowSpan} className={`th px-3 py-2 ${className}`}>
      {key ? (
        <button onClick={() => sortBy(key)} className="inline-flex items-center gap-1 uppercase hover:text-text">
          {children}
          {q.sort_by === key && (q.sort_dir === "desc" ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
        </button>
      ) : children}
    </th>
  );

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel2 p-2.5">
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-2 text-muted" />
          <input
            value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Search driver ID, city name or city ID"
            className="w-56 rounded-md border border-line bg-panel py-1.5 pl-8 pr-2 text-[13px]"
          />
        </div>
        <select value={q.kind} onChange={(e) => setQ({ kind: e.target.value, page: 0 })}
          className="rounded-md border border-line bg-panel px-2 py-1.5 text-[13px]">
          <option value="">Temporary + permanent</option>
          <option value="temporary">Temporary only</option>
          <option value="permanent">Permanent only</option>
        </select>
        {focusLabel && (
          <button onClick={onClearFocus}
            className="flex items-center gap-1 rounded-full bg-accentsoft px-2.5 py-1 text-[12px] font-medium text-accent">
            {focusLabel} <X size={12} />
          </button>
        )}
        <a
          href={api.exportUrl({ horizon_days: horizon, country: q.country, city_id: q.city_id, kind: q.kind })}
          className="ml-auto flex items-center gap-1.5 rounded-md border border-line bg-panel px-2.5 py-1.5 text-[13px] hover:bg-panel2"
        >
          <Download size={14} /> Export CSV (all {total.toLocaleString("en-US")})
        </a>
      </div>

      <div className="overflow-auto">
        <table className="tnum w-full min-w-[1180px] border-collapse text-[13px]">
          <thead className="bg-panel2">
            <tr className="border-b border-line">
              {h("driver_id", "text-left align-bottom", "Driver", { rowSpan: 2 })}
              {h("city_name", "text-left align-bottom", "City", { rowSpan: 2 })}
              {h(null, "text-left align-bottom", "Segment", { rowSpan: 2 })}
              {h("block_hours", "text-left align-bottom", "Block", { rowSpan: 2 })}
              <th colSpan={3} className="th border-l border-line px-3 pt-2 text-center">Short term &middot; per week</th>
              <th colSpan={4} className="th border-l border-line px-3 pt-2 text-center">Over {horizon} days</th>
            </tr>
            <tr className="border-b border-line">
              {h("trips_week", "border-l border-line text-right", "Trips")}
              {h("tsh_week", "text-right", "TSH")}
              {h("gmv_week", "text-right", "GMV")}
              {h("lost_trips", "border-l border-line text-right", "Trips")}
              {h("lost_tsh", "text-right", "TSH")}
              {h("lost_gmv", "text-right", "GMV")}
              {h("lost_net", "text-right", "Economic loss")}
            </tr>
          </thead>
          <tbody className={loading ? "opacity-50" : ""}>
            {data?.rows.map((r) => (
              <tr key={`${r.country_code}:${r.driver_id}`} className="border-b border-line/70 hover:bg-panel2">
                <td className="px-3 py-1.5">
                  <span className="font-mono text-[12px]">{r.driver_id}</span>{" "}
                  <span className="text-[11px] text-muted">{r.country_code}</span>
                </td>
                <td className="px-3 py-1.5">{r.city_name}</td>
                <td className="px-3 py-1.5 text-[12px] text-muted">{r.segment}</td>
                <td className="px-3 py-1.5">
                  <span className="font-medium" style={{ color: KIND_COLOR[r.block_kind] }}>{KIND_LABEL[r.block_kind]}</span>
                  {r.block_kind === "temporary" && <span className="text-muted"> &middot; {int(r.block_hours)} h</span>}
                </td>
                <td className="border-l border-line px-3 py-1.5 text-right">{dec(r.trips_week)}</td>
                <td className="px-3 py-1.5 text-right">{dec(r.tsh_week)}</td>
                <td className="px-3 py-1.5 text-right">{moneyCompact(r.gmv_week)}</td>
                <td className="border-l border-line px-3 py-1.5 text-right">{compact(r.lost_trips)}</td>
                <td className="px-3 py-1.5 text-right">{compact(r.lost_tsh)}</td>
                <td className="px-3 py-1.5 text-right">{moneyCompact(r.lost_gmv)}</td>
                <td
                  className="px-3 py-1.5 text-right font-semibold"
                  title={`GMV ${moneyCompact(r.lost_gmv)} − CX cost avoided ${moneyCompact(r.cx_cost_avoided)} (${r.tickets} tickets/28d, $${r.compensated_usd.toFixed(2)} compensated/28d)`}
                >
                  {moneyCompact(r.lost_net)}
                </td>
              </tr>
            ))}
            {!loading && !data?.rows.length && (
              <tr><td colSpan={11} className="px-3 py-8 text-center text-muted">No drivers match these filters</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line bg-panel2 px-3 py-2 text-[12px] text-muted">
        <span>{total.toLocaleString("en-US")} blocked drivers &middot; click a column header to sort (server-side)</span>
        <div className="flex items-center gap-2">
          <select value={q.page_size} onChange={(e) => setQ({ page_size: Number(e.target.value), page: 0 })}
            className="rounded border border-line bg-panel px-1.5 py-0.5">
            {[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n} / page</option>)}
          </select>
          <button disabled={q.page === 0} onClick={() => setQ({ page: q.page - 1 })}
            className="rounded border border-line bg-panel p-1 disabled:opacity-40"><ChevronLeft size={14} /></button>
          <span className="tnum">Page {(q.page + 1).toLocaleString("en-US")} of {pages.toLocaleString("en-US")}</span>
          <button disabled={q.page + 1 >= pages} onClick={() => setQ({ page: q.page + 1 })}
            className="rounded border border-line bg-panel p-1 disabled:opacity-40"><ChevronRight size={14} /></button>
        </div>
      </div>
    </div>
  );
}
