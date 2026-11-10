import type { ReactNode } from "react";
import { STATUS_BG, STATUS_FG, STATUS_LABEL, type Status } from "@/lib/format";

export function Section({
  id, title, subtitle, right, children,
}: { id?: string; title: string; subtitle?: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-text">{title}</h2>
          {subtitle && <p className="mt-0.5 max-w-3xl text-[13px] text-muted">{subtitle}</p>}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

export function StatusPill({ status, label }: { status: Status; label?: string }) {
  return (
    <span
      className="inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold"
      style={{ color: STATUS_FG[status], background: STATUS_BG[status] }}
    >
      {label ?? STATUS_LABEL[status]}
    </span>
  );
}

/** Fully absorbed, or how many of the lost weekly trips the remaining drivers can cover. */
export function Absorption({ lost, capacity }: { lost: number; capacity: number }) {
  if (lost <= 0) return <span className="text-[12px] text-muted">{"–"}</span>;
  const n = (x: number) => Math.round(x).toLocaleString("en-US");
  if (capacity >= lost) return <StatusPill status="green" label="Absorbed" />;
  const absorbed = Math.max(capacity, 0);
  return (
    <span className="tnum whitespace-nowrap text-[12px]">
      <StatusPill status={absorbed > 0 ? "yellow" : "red"} label={absorbed > 0 ? "Partly" : "None"} />{" "}
      <b>{n(absorbed)}</b> of {n(lost)} trips/wk
    </span>
  );
}

export function KindDots({ temporary, permanent }: { temporary: number; permanent: number }) {
  return (
    <span className="tnum whitespace-nowrap text-[12px] text-muted">
      <span style={{ color: "var(--temp)" }}>{temporary}</span>
      {" / "}
      <span style={{ color: "var(--perm)" }}>{permanent}</span>
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="card px-6 py-10 text-center text-sm text-muted">{children}</div>;
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border px-4 py-3 text-sm" style={{ color: "var(--red)", background: "var(--red-soft)", borderColor: "#f5c2bf" }}>
      {children}
    </div>
  );
}
