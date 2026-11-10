"use client";

import { FileUp, Loader2, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import type { BlocklistReport } from "@/lib/api";
import { ErrorBox } from "./ui";

const n = (x: number) => x.toLocaleString("en-US");

export default function UploadCard({
  report, uploading, error, onFile, onClear, disabled,
}: {
  report: BlocklistReport | null | undefined;
  uploading: boolean;
  error: string | null;
  onFile: (f: File) => void;
  onClear: () => void;
  disabled: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const pick = (f: File | undefined) => f && onFile(f);

  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-start gap-4">
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
          onClick={() => !disabled && input.current?.click()}
          className={`flex min-w-[280px] flex-1 cursor-pointer items-center gap-3 rounded-lg border-2 border-dashed px-4 py-4 transition-colors ${
            drag ? "border-accent bg-accentsoft" : "border-line bg-panel2 hover:border-accent"
          } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
        >
          {uploading ? <Loader2 className="animate-spin text-accent" size={22} /> : <FileUp className="text-accent" size={22} />}
          <div>
            <div className="text-sm font-medium">
              {report ? "Replace the list of blocked drivers" : "Upload the list of blocked drivers (CSV)"}
            </div>
            <div className="text-[12px] text-muted">
              Columns: <code className="rounded bg-line/60 px-1">driver_id</code> and{" "}
              <code className="rounded bg-line/60 px-1">block_hours</code> (hours blocked;{" "}
              <b>9999 = permanent</b>)
            </div>
          </div>
          <input ref={input} type="file" accept=".csv,text/csv" hidden
            onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
        </div>

        {report && (
          <div className="min-w-[260px] flex-1 text-[13px]">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{report.filename ?? "List loaded"}</span>
              <button onClick={onClear} className="flex items-center gap-1 text-[12px] text-muted hover:text-danger">
                <Trash2 size={13} /> Remove
              </button>
            </div>
            <ul className="mt-1.5 space-y-0.5 text-muted">
              <li>
                <b className="tnum text-text">{n(report.count)}</b> drivers &middot;{" "}
                <span style={{ color: "var(--temp)" }}>{n(report.temporary)} temporary</span> &middot;{" "}
                <span style={{ color: "var(--perm)" }}>{n(report.permanent)} permanent</span>
              </li>
              {report.matched != null && (
                <li>
                  <b className="tnum text-text">{n(report.matched)}</b> found in the driver base
                  {!!report.unmatched_count && (
                    <span className="text-warn">
                      {" "}&middot; {n(report.unmatched_count)} not found
                      {report.unmatched_sample?.length ? ` (e.g. ${report.unmatched_sample.slice(0, 3).join(", ")})` : ""}
                    </span>
                  )}
                </li>
              )}
              {!!report.ambiguous_count && (
                <li className="text-warn">
                  {n(report.ambiguous_count)} driver_ids appear in more than one country: they are counted in each.
                </li>
              )}
              {!!report.rows_invalid && (
                <li className="text-warn">
                  {n(report.rows_invalid)} rows ignored (empty id or invalid hours)
                  {report.invalid_sample.length ? `, e.g. ${report.invalid_sample.slice(0, 3).join(", ")}` : ""}
                </li>
              )}
              {!!report.duplicate_rows && (
                <li>{n(report.duplicate_rows)} repeated rows: the longest block of each driver is used.</li>
              )}
            </ul>
          </div>
        )}
      </div>
      {error && <div className="mt-3"><ErrorBox>{error}</ErrorBox></div>}
    </div>
  );
}
