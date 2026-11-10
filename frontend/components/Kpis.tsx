import type { Summary } from "@/lib/api";
import { compact, int, moneyCompact, pct } from "@/lib/format";

function Tile({ label, value, sub, strong = false }: { label: string; value: string; sub?: string; strong?: boolean }) {
  return (
    <div className={`card px-4 py-3 ${strong ? "border-accent/40 bg-accentsoft/40" : ""}`}>
      <div className="th">{label}</div>
      <div className="tnum mt-1 text-2xl font-semibold">{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-muted">{sub}</div>}
    </div>
  );
}

export default function Kpis({ s }: { s: Summary }) {
  const h = s.horizon_days;
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 flex items-baseline gap-2">
          <h3 className="text-sm font-semibold">Short term</h3>
          <span className="text-[12px] text-muted">weekly average of the last 4 weeks, while blocked</span>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Tile label="Blocked drivers" value={int(s.blocked_drivers)}
            sub={`${pct(s.blocked_drivers / Math.max(s.total_drivers, 1), 2)} of ${compact(s.total_drivers)} drivers`} />
          <Tile label="Trips / week" value={compact(s.lost_trips_week)} sub={`${pct(s.market_share_lost)} of all trips`} />
          <Tile label="TSH / week" value={compact(s.lost_tsh_week)} />
          <Tile label="GMV / week" value={moneyCompact(s.lost_gmv_week)} sub={"trips × IPT"} />
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-baseline gap-2">
          <h3 className="text-sm font-semibold">Over {h} days</h3>
          <span className="text-[12px] text-muted">
            weekly rate projected forward; temporary blocks only count the hours they last
          </span>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Tile label={`Trips, ${h} d`} value={compact(s.lost_trips)} />
          <Tile label={`TSH, ${h} d`} value={compact(s.lost_tsh)} />
          <Tile label={`GMV, ${h} d`} value={moneyCompact(s.lost_gmv)} />
          <Tile strong label={`Economic loss, ${h} d`} value={moneyCompact(s.lost_net)}
            sub={`GMV − ${moneyCompact(s.cx_cost_avoided)} CX cost avoided`} />
        </div>
      </div>

      <div className="grid gap-3">
        <div className="card px-4 py-3">
          <div className="th">How concentrated is the loss?</div>
          <div className="tnum mt-1.5 text-[13px]">
            Top <b>1%</b> of blocked drivers = <b>{pct(s.top1_share_gmv, 0)}</b> of GMV loss &middot; top <b>10%</b> ={" "}
            <b>{pct(s.top10_share_gmv, 0)}</b>
          </div>
          <div className="mt-1 text-[12px] text-muted">
            If a few drivers carry most of the loss, review those first (Drivers table is sorted by economic loss).
          </div>
        </div>
      </div>
    </div>
  );
}
