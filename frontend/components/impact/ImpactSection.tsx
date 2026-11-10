"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Empty, ErrorBox } from "@/components/ui";
import { impactApi, type Group, type RuleCell } from "@/lib/api";
import { int, pct } from "@/lib/format";
import { GROUP_COLOR } from "./colors";

type Metric = keyof RuleCell;
const METRICS: { key: Metric; label: string }[] = [
  { key: "drivers", label: "Impacted drivers" },
  { key: "active", label: "Active drivers" },
  { key: "trips", label: "Trips" },
  { key: "sh", label: "Supply hours (TSH)" },
];
const TOTAL = "Total SSL";
/** Column order: all SSL first, then the regions. */
const GROUP_ORDER: Group[] = ["Total SSL", "MX", "AR", "CO", "Rest of SSL"];
const PAGE = 100;

/** Block impact: rows = the rule behind the block, columns = region (MX, AR, CO, Rest of SSL, All SSL).
 *  Each region shows the volume over the whole window and the share of that region the rule represents. */
export default function ImpactSection() {
  const [metric, setMetric] = useState<Metric>("active"); // default: active drivers
  const [level, setLevel] = useState("category_four_name");
  const [search, setSearch] = useState("");
  const [shown, setShown] = useState(PAGE);

  const q = useQuery({
    queryKey: ["impact-by-rule", level],
    queryFn: () => impactApi.impactByRule({ level }),
    placeholderData: (prev) => prev,
  });
  const s = q.data;
  const groups = useMemo(() => (s ? GROUP_ORDER.filter((g) => s.groups.includes(g)) : []), [s]);

  // rows sorted by the all-SSL volume of the selected metric; search filters by rule name
  const rows = useMemo(() => {
    if (!s) return [];
    const needle = search.trim().toLowerCase();
    const list = needle ? s.rows.filter((r) => r.rule.toLowerCase().includes(needle)) : [...s.rows];
    return list.sort((a, b) => b.totals[TOTAL][metric] - a.totals[TOTAL][metric]);
  }, [s, search, metric]);

  // largest share per region among the visible rows, to scale the little bars
  const maxShare = useMemo(() => {
    const out: Record<string, number> = {};
    if (!s) return out;
    for (const g of groups) {
      const tot = s.all[g][metric];
      out[g] = tot > 0 ? Math.max(0, ...rows.slice(0, shown).map((r) => r.totals[g][metric] / tot)) : 0;
    }
    return out;
  }, [s, groups, rows, shown, metric]);

  if (q.error) return <ErrorBox>{(q.error as Error).message}</ErrorBox>;
  if (!s) return <Empty>Loading&hellip;</Empty>;

  const seg = (active: boolean) => `rounded px-3 py-1 ${active ? "bg-accent text-white" : "text-muted hover:text-text"}`;
  const sel = "rounded-md border border-line bg-panel px-2 py-1.5 text-[13px]";
  const visible = rows.slice(0, shown);
  const metricLabel = METRICS.find((m) => m.key === metric)?.label ?? "";
  const label = (g: string) => (g === TOTAL ? "All SSL" : g);

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel2 px-3 py-2.5">
        <div className="flex rounded-md border border-line bg-panel p-0.5 text-[13px]">
          {METRICS.map((m) => (
            <button key={m.key} onClick={() => setMetric(m.key)} className={seg(metric === m.key)}>{m.label}</button>
          ))}
        </div>
        <select value={level} onChange={(e) => { setLevel(e.target.value); setShown(PAGE); }} className={sel}
          aria-label="Rule level" title="Which level of the rule hierarchy the rows show">
          {s.level_options.map((o) => <option key={o.key} value={o.key}>Rows: {o.label}</option>)}
        </select>
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-2 text-muted" />
          <input value={search} onChange={(e) => { setSearch(e.target.value); setShown(PAGE); }}
            placeholder="Search rule" className="w-52 rounded-md border border-line bg-panel py-1.5 pl-8 pr-2 text-[13px]" />
        </div>
        <span className="text-[12px] text-muted">
          {s.n_rules.toLocaleString("en-US")} rules &middot; {s.n_weeks} weeks
          {s.first_week && <> ({s.first_week} &rarr; {s.last_week})</>} in total
        </span>
      </div>

      <div className="max-h-[640px] overflow-auto">
        <table className="tnum w-full border-collapse text-[12px]" style={{ minWidth: 260 + groups.length * 170 }}>
          <thead className="sticky top-0 z-10 bg-panel2">
            <tr className="border-b border-line">
              <th rowSpan={2} className="th sticky left-0 z-20 min-w-[240px] bg-panel2 px-3 py-2 text-left align-bottom">
                {s.level_options.find((o) => o.key === s.level)?.label}
              </th>
              {groups.map((g) => (
                <th key={g} colSpan={2}
                  className={`th border-l border-line px-3 pt-2 text-center ${g === TOTAL ? "bg-accentsoft/60" : ""}`}>
                  <i className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ background: GROUP_COLOR[g] }} />
                  {label(g)}
                </th>
              ))}
            </tr>
            <tr className="border-b border-line">
              {groups.map((g) => (
                <FragmentHeads key={g} g={g} total={g === TOTAL} />
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-line bg-panel2 font-semibold">
              <td className="sticky left-0 bg-panel2 px-3 py-1.5">All rules <span className="font-normal text-muted">(total)</span></td>
              {groups.map((g) => (
                <FragmentCells key={g} total={g === TOTAL} volume={s.all[g][metric]} share={s.all[g][metric] > 0 ? 1 : null} bar={0} bold />
              ))}
            </tr>
            {visible.map((r) => (
              <tr key={r.rule} className="border-b border-line/60 hover:bg-accentsoft/40">
                <td className="sticky left-0 max-w-[340px] truncate bg-panel px-3 py-1.5 font-medium" title={r.rule}>{r.rule}</td>
                {groups.map((g) => {
                  const regionTotal = s.all[g][metric];
                  const v = r.totals[g][metric];
                  const share = regionTotal > 0 ? v / regionTotal : null;
                  const bar = share != null && maxShare[g] > 0 ? share / maxShare[g] : 0;
                  return <FragmentCells key={g} total={g === TOTAL} volume={v} share={share} bar={bar} />;
                })}
              </tr>
            ))}
            {!visible.length && (
              <tr><td colSpan={groups.length * 2 + 1} className="px-3 py-8 text-center text-muted">No rules for this selection</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {rows.length > visible.length && (
        <div className="border-t border-line bg-panel2 px-3 py-2 text-center">
          <button onClick={() => setShown((n) => n + PAGE * 2)} className="text-[13px] font-medium text-accent hover:underline">
            Show more ({(rows.length - visible.length).toLocaleString("en-US")} remaining)
          </button>
        </div>
      )}
      <p className="border-t border-line bg-panel2 px-3 py-2 text-[12px] text-muted">
        {metricLabel}, added up over the {s.n_weeks} weeks of the window. <b>Volume</b> = the rule&rsquo;s total in that region;
        <b> %</b> = the rule&rsquo;s share of that region&rsquo;s total. Impacted = drivers with at least one block in a week; active =
        those who also completed a trip; trips and TSH are those drivers&rsquo; activity. A driver blocked by two rules, or in two
        weeks, is counted in each, so &ldquo;All rules&rdquo; is the sum of the rows, not a de-duplicated head count.
        {s.truncated && " Only the 300 rules with the most impacted drivers are shown."}
      </p>
    </div>
  );
}

function FragmentHeads({ g, total }: { g: string; total: boolean }) {
  const bg = total ? "bg-accentsoft/60" : "";
  return (
    <>
      <th className={`th border-l border-line px-3 py-1.5 text-right ${bg}`}>Volume</th>
      <th className={`th px-3 py-1.5 text-right ${bg}`} title={`Share of ${g === TOTAL ? "all SSL" : g}`}>%</th>
    </>
  );
}

function FragmentCells({
  volume, share, bar, total, bold = false,
}: { volume: number; share: number | null; bar: number; total: boolean; bold?: boolean }) {
  const bg = total ? "bg-accentsoft/30" : "";
  return (
    <>
      <td className={`border-l border-line px-3 py-1.5 text-right ${bold ? "" : "font-medium"} ${bg} ${volume ? "" : "text-muted"}`}>
        {volume ? int(volume) : "–"}
      </td>
      <td className={`px-3 py-1.5 text-right ${bg} ${share ? "" : "text-muted"}`}
        style={bar > 0 ? { background: `linear-gradient(90deg, rgba(36,89,214,0.16) ${bar * 100}%, transparent ${bar * 100}%)` } : undefined}>
        {share == null || volume === 0 ? "–" : pct(share, 1)}
      </td>
    </>
  );
}
