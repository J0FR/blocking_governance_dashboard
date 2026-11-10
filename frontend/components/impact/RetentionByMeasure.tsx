"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Empty, ErrorBox } from "@/components/ui";
import { impactApi, type MeasureCell } from "@/lib/api";
import { int, pct } from "@/lib/format";

const MIN_N = 30; // cells with fewer eligible drivers are dimmed (noisy)

/** Sequential blue scale relative to the highest rate in the table: low = near white, high = accent. */
function shade(rate: number | null | undefined, max: number): { bg: string; fg: string } {
  if (rate == null) return { bg: "transparent", fg: "var(--muted)" };
  const a = max > 0 ? Math.min(rate / max, 1) : 0;
  return { bg: `rgba(36, 89, 214, ${0.06 + a * 0.84})`, fg: a > 0.55 ? "#fff" : "var(--text)" };
}

function Cell({ c, max }: { c: MeasureCell | undefined; max: number }) {
  if (!c || c.rate == null) return <td className="px-2 py-1 text-center text-muted">–</td>;
  const s = shade(c.rate, max);
  return (
    <td className="px-2 py-1 text-center" title={`${int(c.returned)} returned / ${int(c.eligible)} eligible`}
      style={{ background: s.bg, color: s.fg, opacity: c.eligible < MIN_N ? 0.55 : 1 }}>
      {pct(c.rate, 1)}
    </td>
  );
}

/** Retention by measure.
 *  Rows    = category_four_name (the measure)
 *  Columns = retention window (retention_order, with retention_window_weeks / retention_window_days)
 *  Value   = returned_drivers_general / eligible_drivers_general, summed over all cohort weeks first. */
export default function RetentionByMeasure() {
  const [country, setCountry] = useState("");
  const [measure, setMeasure] = useState("");

  const q = useQuery({
    queryKey: ["retention-by-measure", country, measure],
    queryFn: () => impactApi.retentionByMeasure({ country, measure }),
    placeholderData: (prev) => prev,
  });
  const s = q.data;

  const max = useMemo(() => {
    let m = 0;
    for (const r of s?.rows ?? []) for (const c of Object.values(r.cells)) if (c.rate != null && c.rate > m) m = c.rate;
    return m;
  }, [s]);

  if (q.error) return <ErrorBox>{(q.error as Error).message}</ErrorBox>;
  if (!s) return <Empty>Loading&hellip;</Empty>;

  const sel = "rounded-md border border-line bg-panel px-2 py-1.5 text-[13px]";
  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel2 px-3 py-2">
        <div className="mr-2 text-[13px] font-medium">Retention by measure</div>
        <select value={country} onChange={(e) => setCountry(e.target.value)} className={sel} aria-label="Country">
          <option value="">All countries</option>
          {s.country_options.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={measure} onChange={(e) => setMeasure(e.target.value)} className={`${sel} max-w-[320px]`} aria-label="Measure">
          <option value="">All measures</option>
          {s.measure_options.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      <p className="px-3 pt-2 text-[12px] text-muted">
        returned_drivers_general &divide; eligible_drivers_general, summed over all cohort weeks. Hover a cell for returned /
        eligible; cells under {MIN_N} eligible drivers are dimmed.
      </p>
      <div className="overflow-auto">
        <table className="tnum w-full border-collapse text-[12px]" style={{ minWidth: 260 + s.windows.length * 78 }}>
          <thead className="bg-panel2">
            <tr className="border-b border-line">
              <th className="th sticky left-0 z-10 bg-panel2 px-3 py-2 text-left align-bottom">Measure (category_four_name)</th>
              <th className="th px-2 py-2 text-right align-bottom">Eligible</th>
              {s.windows.map((w) => (
                <th key={w.order} className="th px-2 py-2 text-center">
                  {w.weeks}
                  <div className="font-normal normal-case text-[11px] text-muted">{w.days}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-line bg-panel2 font-semibold">
              <td className="sticky left-0 bg-panel2 px-3 py-1.5">All selected</td>
              <td className="px-2 py-1.5 text-right text-muted">{int(Math.max(0, ...Object.values(s.total).map((c) => c.eligible)))}</td>
              {s.windows.map((w) => <Cell key={w.order} c={s.total[String(w.order)]} max={max} />)}
            </tr>
            {s.rows.map((r) => (
              <tr key={r.measure} className="border-b border-line/60">
                <td className="sticky left-0 max-w-[340px] truncate bg-panel px-3 py-1 font-medium" title={r.measure}>{r.measure}</td>
                <td className="px-2 py-1 text-right text-muted">{int(r.eligible)}</td>
                {s.windows.map((w) => <Cell key={w.order} c={r.cells[String(w.order)]} max={max} />)}
              </tr>
            ))}
            {!s.rows.length && (
              <tr><td colSpan={s.windows.length + 2} className="px-3 py-8 text-center text-muted">No data for this selection</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
