"use client";

import { useState } from "react";
import type { ProfileDim, ProfileRow } from "@/lib/api";
import { compact, int, KIND_LABEL, moneyCompact, pct } from "@/lib/format";

const DIMS: { key: ProfileDim; label: string }[] = [
  { key: "seg_supply_hours", label: "Online hours" },
  { key: "seg_ipt", label: "IPT" },
  { key: "seg_incentive", label: "Incentive" },
  { key: "seg_shor", label: "SHOR" },
  { key: "vehicle_type", label: "Vehicle" },
  { key: "country_code", label: "Country" },
  { key: "block_kind", label: "Block type" },
];

export default function Profile({
  profile, horizon,
}: { profile: Record<ProfileDim, ProfileRow[]>; horizon: number }) {
  const [dim, setDim] = useState<ProfileDim>("seg_supply_hours");
  const rows = profile[dim] ?? [];
  const maxShare = Math.max(...rows.map((r) => r.share_of_blocked), 0.0001);
  const name = (v: string) => (dim === "block_kind" ? KIND_LABEL[v as keyof typeof KIND_LABEL] ?? v : v);

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap gap-1 border-b border-line bg-panel2 p-2">
        {DIMS.map((d) => (
          <button
            key={d.key} onClick={() => setDim(d.key)}
            className={`rounded-md px-3 py-1 text-[13px] ${dim === d.key ? "bg-accent text-white" : "text-muted hover:bg-line/50 hover:text-text"}`}
          >
            {d.label}
          </button>
        ))}
      </div>
      <div className="overflow-auto">
        <table className="tnum w-full min-w-[960px] border-collapse text-[13px]">
          <thead>
            <tr className="border-b border-line">
              <th className="th px-3 py-2 text-left">Segment</th>
              <th className="th px-3 py-2 text-left">Share of blocked</th>
              <th className="th px-3 py-2 text-right">Blocked</th>
              <th className="th px-3 py-2 text-right">% of its base</th>
              <th className="th px-3 py-2 text-right">Avg trips/wk</th>
              <th className="th px-3 py-2 text-right">Avg IPT</th>
              <th className="th px-3 py-2 text-right">Trips {horizon}d</th>
              <th className="th px-3 py-2 text-right">TSH {horizon}d</th>
              <th className="th px-3 py-2 text-right">GMV {horizon}d</th>
              <th className="th px-3 py-2 text-right">Economic loss {horizon}d</th>
              <th className="th px-3 py-2 text-right">Tickets</th>
              <th className="th px-3 py-2 text-right">Compens. USD</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.value} className="border-b border-line/70">
                <td className="px-3 py-1.5 font-medium">{name(r.value)}</td>
                <td className="px-3 py-1.5">
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-28 overflow-hidden rounded-full bg-line">
                      <div className="h-full rounded-full bg-accent" style={{ width: `${(r.share_of_blocked / maxShare) * 100}%` }} />
                    </div>
                    <span className="w-12 text-right text-[12px]">{pct(r.share_of_blocked, 0)}</span>
                  </div>
                </td>
                <td className="px-3 py-1.5 text-right">{int(r.blocked)}</td>
                <td className="px-3 py-1.5 text-right text-muted">{pct(r.blocked_rate, 1)}</td>
                <td className="px-3 py-1.5 text-right">{compact(r.avg_trips_week)}</td>
                <td className="px-3 py-1.5 text-right">{r.avg_ipt != null ? "$" + r.avg_ipt.toFixed(2) : "–"}</td>
                <td className="px-3 py-1.5 text-right">{compact(r.lost_trips)}</td>
                <td className="px-3 py-1.5 text-right">{compact(r.lost_tsh)}</td>
                <td className="px-3 py-1.5 text-right">{moneyCompact(r.lost_gmv)}</td>
                <td className="px-3 py-1.5 text-right font-semibold">{moneyCompact(r.lost_net)}</td>
                <td className="px-3 py-1.5 text-right">{int(r.tickets)}</td>
                <td className="px-3 py-1.5 text-right">{moneyCompact(r.compensated_usd)}</td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={12} className="px-3 py-8 text-center text-muted">No data</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="border-t border-line bg-panel2 px-3 py-2 text-[12px] text-muted">
        &ldquo;% of its base&rdquo; = blocked drivers in the segment &divide; all drivers in that segment in the 28-day base.
        Tickets and compensations are from that same period.
      </p>
    </div>
  );
}
