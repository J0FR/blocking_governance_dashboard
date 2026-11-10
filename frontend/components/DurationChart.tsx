"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DurationRow } from "@/lib/api";
import { compact, int, KIND_COLOR, moneyCompact } from "@/lib/format";

type Metric = "lost_net" | "lost_gmv" | "lost_trips" | "lost_tsh" | "drivers";
const METRICS: { key: Metric; label: string; fmt: (n: number) => string }[] = [
  { key: "lost_net", label: "Economic loss", fmt: moneyCompact },
  { key: "lost_gmv", label: "GMV", fmt: moneyCompact },
  { key: "lost_trips", label: "Trips", fmt: compact },
  { key: "lost_tsh", label: "TSH", fmt: compact },
  { key: "drivers", label: "Drivers", fmt: int },
];

export default function DurationChart({ rows, horizon }: { rows: DurationRow[]; horizon: number }) {
  const [metric, setMetric] = useState<Metric>("lost_net");
  const m = METRICS.find((x) => x.key === metric)!;
  const data = rows.map((r) => ({ ...r, value: r[metric] }));
  const isMoney = metric === "lost_net" || metric === "lost_gmv";

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="card p-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="text-sm font-medium">Loss over {horizon} days by block duration</div>
          <div className="flex rounded-md border border-line p-0.5 text-[12px]">
            {METRICS.map((x) => (
              <button
                key={x.key} onClick={() => setMetric(x.key)}
                className={`rounded px-2 py-0.5 ${metric === x.key ? "bg-accent text-white" : "text-muted hover:text-text"}`}
              >
                {x.label}
              </button>
            ))}
          </div>
        </div>
        <div style={{ height: 280 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#e4e7ec" vertical={false} />
              <XAxis dataKey="bucket" tick={{ fill: "#667085", fontSize: 12 }} axisLine={{ stroke: "#d0d5dd" }} tickLine={false} />
              <YAxis tick={{ fill: "#667085", fontSize: 12 }} axisLine={false} tickLine={false} width={56}
                tickFormatter={(v) => (isMoney ? moneyCompact(v) : compact(v))} />
              <Tooltip
                cursor={{ fill: "rgba(36,89,214,0.06)" }}
                contentStyle={{ background: "#fff", border: "1px solid #e4e7ec", borderRadius: 8, fontSize: 12 }}
                formatter={(v) => [m.fmt(Number(v)), m.label]}
              />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {data.map((r) => <Cell key={r.bucket} fill={KIND_COLOR[r.kind]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-1 flex gap-4 text-[12px] text-muted">
          <span><i className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: "var(--temp)" }} />Temporary</span>
          <span><i className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: "var(--perm)" }} />Permanent</span>
        </div>
      </div>

      <div className="card overflow-hidden">
        <table className="tnum w-full border-collapse text-[13px]">
          <thead className="bg-panel2">
            <tr className="border-b border-line">
              <th className="th px-3 py-2 text-left">Duration</th>
              <th className="th px-3 py-2 text-right">Drivers</th>
              <th className="th px-3 py-2 text-right">Trips</th>
              <th className="th px-3 py-2 text-right">TSH</th>
              <th className="th px-3 py-2 text-right">GMV</th>
              <th className="th px-3 py-2 text-right">Economic loss</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.bucket} className={`border-b border-line/70 ${r.drivers === 0 ? "text-muted" : ""}`}>
                <td className="px-3 py-1.5">
                  <i className="mr-2 inline-block h-2 w-2 rounded-sm" style={{ background: KIND_COLOR[r.kind] }} />
                  {r.bucket}
                </td>
                <td className="px-3 py-1.5 text-right">{int(r.drivers)}</td>
                <td className="px-3 py-1.5 text-right">{compact(r.lost_trips)}</td>
                <td className="px-3 py-1.5 text-right">{compact(r.lost_tsh)}</td>
                <td className="px-3 py-1.5 text-right">{moneyCompact(r.lost_gmv)}</td>
                <td className="px-3 py-1.5 text-right font-semibold">{moneyCompact(r.lost_net)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="border-t border-line bg-panel2 px-3 py-2 text-[12px] text-muted">
          Temporary: the driver&rsquo;s hourly rate (per calendar hour) &times; hours blocked (capped at {horizon} d).
          Permanent: that rate over the full {horizon} days.
        </p>
      </div>
    </div>
  );
}
