const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const DASH = "–";

export const int = (n: number | null | undefined) => (n == null ? DASH : nf0.format(n));
export const dec = (n: number | null | undefined) => (n == null ? DASH : nf1.format(n));
export const pct = (n: number | null | undefined, d = 1) => (n == null ? DASH : (n * 100).toFixed(d) + "%");
const sign = (n: number) => (n < 0 ? "−" : "");
export const money = (n: number | null | undefined) => (n == null ? DASH : sign(n) + "$" + nf0.format(Math.abs(n)));

export const compact = (n: number | null | undefined) => {
  if (n == null) return DASH;
  const a = Math.abs(n);
  if (a >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (a >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return nf0.format(n);
};
export const moneyCompact = (n: number | null | undefined) =>
  n == null ? DASH : sign(n) + "$" + compact(Math.abs(n));

export type Status = "red" | "yellow" | "green" | "none";

export const STATUS_LABEL: Record<Status, string> = {
  red: "Not absorbed",
  yellow: "Tight",
  green: "Absorbed",
  none: "No impact",
};

export const STATUS_FG: Record<Status, string> = {
  red: "var(--red)",
  yellow: "var(--yellow)",
  green: "var(--green)",
  none: "var(--muted)",
};

export const STATUS_BG: Record<Status, string> = {
  red: "var(--red-soft)",
  yellow: "var(--yellow-soft)",
  green: "var(--green-soft)",
  none: "var(--panel-2)",
};

export const KIND_LABEL = { temporary: "Temporary", permanent: "Permanent" } as const;
export const KIND_COLOR = { temporary: "var(--temp)", permanent: "var(--perm)" } as const;

export const cityKey = (c: { country_code: string; city_id: number | null }) =>
  `${c.country_code}:${c.city_id ?? "NA"}`;
