import type { Status } from "./format";

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const MIN = 60_000;

/** Every call has a timeout: a stuck backend must show an error, never leave a button disabled forever. */
async function req<T>(path: string, init?: RequestInit, timeoutMs = 2 * MIN): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let r: Response;
  try {
    r = await fetch(API + path, { ...init, signal: ctrl.signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error(
        `The API (${API}) did not answer within ${Math.round(timeoutMs / 1000)} s. It may be stuck: restart the backend and try again.`,
      );
    }
    throw new Error(`Could not reach the API (${API}). Is the backend running?`);
  } finally {
    clearTimeout(timer);
  }
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {}
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export type SnapshotMeta = { run_date: string; rows: number; engine: string; seconds: number; refreshed_at: string };

export type BlocklistReport = {
  filename?: string;
  rows_in: number;
  rows_invalid: number;
  invalid_sample: string[];
  duplicate_rows: number;
  count: number;
  temporary: number;
  permanent: number;
  matched?: number;
  unmatched_count?: number;
  unmatched_sample?: string[];
  ambiguous_count?: number;
  snapshot_missing?: boolean;
};

export type Meta = {
  snapshot: SnapshotMeta | null;
  driver_window: { run_date: string; start_date: string; end_date: string };
  horizon_days: number;
  permanent_hours: number;
  ticket_cost_usd: number;
  fx_local_per_usd: Record<string, number>;
  blocklist: BlocklistReport | null;
};

export type Part = { drivers: number; lost_trips: number; lost_tsh: number; lost_gmv: number; lost_net: number };

export type Summary = {
  horizon_days: number;
  ticket_cost_usd: number;
  lost_net: number;
  cx_cost_avoided: number;
  lost_net_week: number;
  top1_share_gmv: number;
  top10_share_gmv: number;
  blocked_drivers: number;
  total_drivers: number;
  lost_trips: number;
  lost_tsh: number;
  lost_gmv: number;
  lost_trips_week: number;
  lost_tsh_week: number;
  lost_gmv_week: number;
  market_share_lost: number;
  temporary: Part;
  permanent: Part;
  cities_affected: number;
  cities_red: number;
  cities_yellow: number;
  cities_green: number;
};

/** Weekly = 4-week average while blocked. lost_* = projected over the horizon (temporary: its own duration). */
export type GeoRow = {
  country_code: string;
  drivers: number;
  trips_week: number;
  tsh_week: number;
  blocked_drivers: number;
  blocked_temporary: number;
  blocked_permanent: number;
  lost_trips_week: number;
  lost_tsh_week: number;
  lost_gmv_week: number;
  lost_trips: number;
  lost_tsh: number;
  lost_gmv: number;
  lost_net: number;
  capacity_trips_week: number;
  capacity_tsh_week: number;
  market_share_lost: number;
  coverage: number | null;
  headroom_trips_week: number;
  status: Status;
};
export type CountryRow = GeoRow & { cities_affected: number };
export type CityRow = GeoRow & { city_id: number | null; city_name: string; headroom_hours_week: number };

export type DurationRow = { bucket: string; kind: "temporary" | "permanent" } & Part;

export type ProfileRow = {
  value: string;
  blocked: number;
  base_drivers: number;
  share_of_blocked: number;
  blocked_rate: number | null;
  lost_trips: number;
  lost_tsh: number;
  lost_gmv: number;
  lost_net: number;
  tickets: number;
  compensated_usd: number;
  avg_ipt: number;
  avg_trips_week: number;
};
export type ProfileDim =
  | "block_kind" | "country_code" | "vehicle_type" | "seg_supply_hours" | "seg_ipt" | "seg_incentive" | "seg_shor";

export type Analysis = {
  match: { matched: number; unmatched_count: number; unmatched_sample: string[]; ambiguous_count: number };
  summary: Summary;
  countries: CountryRow[];
  cities: CityRow[];
  durations: DurationRow[];
  profile: Record<ProfileDim, ProfileRow[]>;
};

export type DriverRow = {
  driver_id: string;
  country_code: string;
  city_id: number | null;
  city_name: string;
  vehicle_type: string;
  segment: string;
  block_kind: "temporary" | "permanent";
  block_hours: number;
  trips_week: number;
  tsh_week: number;
  gmv_week: number;
  net_week: number;
  ipt_eff: number;
  lost_trips: number;
  lost_tsh: number;
  lost_gmv: number;
  cx_cost_avoided: number;
  lost_net: number;
  tickets: number;
  compensated_usd: number;
  occupancy_rate: number | null;
  available_trips: number | null;
};

export type DriverQuery = {
  horizon_days: number;
  search: string;
  country: string;
  city_id: string;
  kind: string;
  sort_by: string;
  sort_dir: "asc" | "desc";
  page: number;
  page_size: number;
};

const qs = (o: Record<string, string | number | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== "") p.set(k, String(v));
  return p.toString();
};

export const api = {
  meta: () => req<Meta>("/meta"),
  refresh: () => req<SnapshotMeta>("/snapshot/refresh", { method: "POST" }, 40 * MIN),
  uploadSnapshot: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<SnapshotMeta>("/snapshot/upload", { method: "POST", body: fd }, 20 * MIN);
  },
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<BlocklistReport>("/blocklist", { method: "POST", body: fd }, 10 * MIN);
  },
  clearBlocklist: () => req<{ ok: boolean }>("/blocklist", { method: "DELETE" }),
  analysis: (horizon_days: number) => req<Analysis>(`/analysis?${qs({ horizon_days })}`),
  drivers: (q: DriverQuery) => req<{ total: number; rows: DriverRow[] }>(`/drivers?${qs(q)}`),
  exportUrl: (q: Pick<DriverQuery, "horizon_days" | "country" | "city_id" | "kind">) =>
    `${API}/export/drivers.csv?${qs(q)}`,
};

// ---------------------------------------------------------------------------
// Block impact + retention (uploaded output of the two Hive queries)
// ---------------------------------------------------------------------------
export type DatasetKind = "impact" | "retention";
/** Queries the dashboard can hand out with the dates already applied. */
export type QueryKind = DatasetKind | "drivers";
export type DatasetMeta = {
  filename: string;
  rows: number;
  weeks: number;
  first_week: string;
  last_week: string;
  countries: string[];
  uploaded_at: string;
};
export type Windows = {
  impact: { start_date: string; end_date: string };
  retention: { start_date: string; end_date: string; data_end_date: string };
};
export type Datasets = { impact: DatasetMeta | null; retention: DatasetMeta | null; windows: Windows };

export type Group = "MX" | "AR" | "CO" | "Rest of SSL" | "Total SSL";
export const GROUPS: Group[] = ["MX", "AR", "CO", "Rest of SSL", "Total SSL"];

export type WeeklyPoint = { group: Group; week: string; drivers: number; active: number; trips: number; sh: number };
export type ImpactRow = {
  group: Group;
  drivers_avg: number;
  active_avg: number;
  trips_avg: number;
  sh_avg: number;
  trips_total: number;
  sh_total: number;
  active_share: number | null;
  trips_per_driver: number | null;
};
export type BreakdownRow = {
  value: string;
  drivers_avg: number;
  active_avg: number;
  trips_avg: number;
  sh_avg: number;
  active_share: number | null;
};
export type ImpactSummary = {
  weeks: string[];
  n_weeks: number;
  weekly: WeeklyPoint[];
  table: ImpactRow[];
  breakdown_dim: string;
  breakdown: BreakdownRow[];
  breakdown_options: { key: string; label: string }[];
};

export type RetentionBase = "general" | "active_14d";
export type CurvePoint = { retention_order: number; eligible: number; returned: number; rate: number | null };
export type RetentionSummary = {
  base: RetentionBase;
  curves: { group: Group; points: CurvePoint[] }[];
  heatmap: { week: string; eligible: number; rates: Record<string, number | null> }[];
  categories: { category: string; eligible: number; w1: number | null; w4: number | null; w8: number | null; w12: number | null }[];
  category_options: string[];
  cohort_weeks: string[];
};

export type MeasureCell = { eligible: number; returned: number; rate: number | null };
export type RetentionWindow = { order: number; weeks: string; days: string };
export type RetentionByMeasure = {
  windows: RetentionWindow[];
  rows: { measure: string; eligible: number; cells: Record<string, MeasureCell> }[];
  total: Record<string, MeasureCell>;
  country_options: string[];
  measure_options: string[];
};

export type RuleCell = { drivers: number; active: number; trips: number; sh: number };
export type ImpactByRule = {
  level: string;
  groups: Group[];
  n_weeks: number;
  first_week: string | null;
  last_week: string | null;
  rows: { rule: string; totals: Record<string, RuleCell> }[];
  n_rules: number;
  truncated: boolean;
  all: Record<string, RuleCell>;
  level_options: { key: string; label: string }[];
};

export const impactApi = {
  datasets: () => req<Datasets>("/datasets"),
  upload: (kind: DatasetKind, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<DatasetMeta>(`/datasets/${kind}`, { method: "POST", body: fd }, 10 * MIN);
  },
  query: (kind: QueryKind) =>
    req<{ kind: QueryKind; sql: string; dates: Record<string, string> }>(`/queries/${kind}`),
  remove: (kind: DatasetKind) => req<{ ok: boolean }>(`/datasets/${kind}`, { method: "DELETE" }),
  impact: (p: { kind: string; group: string; breakdown: string }) => req<ImpactSummary>(`/block-impact?${qs(p)}`),
  impactByRule: (p: { level: string }) =>
    req<ImpactByRule>(`/block-impact/by-rule?${qs(p)}`),
  retention: (p: { base: string; group: string; category: string }) => req<RetentionSummary>(`/retention?${qs(p)}`),
  retentionByMeasure: (p: { country: string; measure: string }) =>
    req<RetentionByMeasure>(`/retention/by-measure?${qs(p)}`),
};
