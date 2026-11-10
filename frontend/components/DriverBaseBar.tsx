"use client";

import { FileUp, Info, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import type { SnapshotMeta } from "@/lib/api";
import { ErrorBox } from "@/components/ui";
import CopyQueryButton from "./impact/CopyQueryButton";

const HINT =
  "The CSV the driver query produces (driver_id, country_code, city_id, city_name, vehicle_type, segment, seg_* columns, " +
  "finished_orders, supply_hours, ipt, avg_trip_minutes, available_trips, available_tsh, occupancy_rate, tickets, compensated_usd). " +
  "Uploading it replaces the current driver base.";

/** Slim bar for the driver base: what is loaded, the query to get a new one, and the upload. */
export default function DriverBaseBar({
  snapshot, windowText, uploading, error, onFile,
}: {
  snapshot: SnapshotMeta | null | undefined;
  windowText: string;
  uploading: boolean;
  error: string | null;
  onFile: (f: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [showHint, setShowHint] = useState(false);
  const pick = (f: File | undefined) => f && onFile(f);

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
      className={`rounded-lg border px-3 py-2 text-[13px] transition-colors ${
        drag ? "border-accent bg-accentsoft" : snapshot ? "border-line bg-panel" : "border-dashed border-line bg-panel2"
      }`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {uploading ? <Loader2 size={15} className="shrink-0 animate-spin text-accent" /> : <FileUp size={15} className="shrink-0 text-muted" />}

        {uploading ? (
          <span className="text-muted">Uploading and processing the driver base&hellip; large files take a minute.</span>
        ) : snapshot ? (
          <>
            <span className="font-medium">Driver base</span>
            <span className="tnum text-muted">
              {snapshot.run_date} &middot; {snapshot.rows.toLocaleString("en-US")} drivers
            </span>
          </>
        ) : (
          <span className="text-muted">No driver base loaded</span>
        )}

        <span className="ml-auto flex items-center gap-3 text-[12px]">
          <span className="hidden text-muted md:inline">
            Query period <span className="tnum text-text">{windowText}</span>
          </span>
          <CopyQueryButton kind="drivers" />
          <button onClick={() => setShowHint((v) => !v)} className="text-muted hover:text-text" title="Required columns">
            <Info size={14} />
          </button>
          <button onClick={() => input.current?.click()} disabled={uploading}
            className="rounded-md border border-line bg-panel px-2 py-0.5 font-medium text-text hover:bg-panel2 disabled:opacity-60">
            {snapshot ? "Replace" : "Upload CSV"}
          </button>
        </span>
        <input ref={input} type="file" accept=".csv,text/csv" hidden
          onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
      </div>

      {showHint && <p className="mt-1.5 text-[12px] text-muted">{HINT} Drag a file onto this bar to upload it.</p>}
      {error && <div className="mt-2"><ErrorBox>{error}</ErrorBox></div>}
    </div>
  );
}
