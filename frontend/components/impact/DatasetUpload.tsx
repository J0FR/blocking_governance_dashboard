"use client";

import { FileUp, Info, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import type { DatasetKind, DatasetMeta } from "@/lib/api";
import CopyQueryButton from "./CopyQueryButton";
import { ErrorBox } from "@/components/ui";

/** Slim one-line upload: never competes with the data below it. */
export default function DatasetUpload({
  kind, title, hint, windowText, meta, expectedWeeks = 12, uploading, error, onFile, onClear, disabled,
}: {
  kind: DatasetKind;
  title: string;
  hint: string;
  windowText: string;
  meta: DatasetMeta | null | undefined;
  expectedWeeks?: number;
  uploading: boolean;
  error: string | null;
  onFile: (f: File) => void;
  onClear: () => void;
  disabled: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [showHint, setShowHint] = useState(false);
  const pick = (f: File | undefined) => f && onFile(f);
  const choose = () => !disabled && input.current?.click();

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
      className={`rounded-lg border px-3 py-2 text-[13px] transition-colors ${
        drag ? "border-accent bg-accentsoft" : meta ? "border-line bg-panel" : "border-dashed border-line bg-panel2"
      }`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {uploading ? <Loader2 size={15} className="shrink-0 animate-spin text-accent" /> : <FileUp size={15} className="shrink-0 text-muted" />}

        {meta ? (
          <>
            <span className="font-medium">{meta.filename}</span>
            <span className="tnum text-muted">
              {meta.rows.toLocaleString("en-US")} rows &middot; weeks {meta.first_week} &rarr; {meta.last_week}
              {meta.weeks !== expectedWeeks && (
                <span className="text-warn"> &middot; expected {expectedWeeks} weeks, found {meta.weeks}</span>
              )}
            </span>
          </>
        ) : (
          <span className="text-muted">No {title} loaded</span>
        )}

        <span className="ml-auto flex items-center gap-3 text-[12px]">
          <span className="hidden text-muted md:inline">
            Query window <span className="tnum text-text">{windowText}</span>
          </span>
          <CopyQueryButton kind={kind} />
          <button onClick={() => setShowHint((v) => !v)} className="text-muted hover:text-text" title="Required columns">
            <Info size={14} />
          </button>
          <button onClick={choose} disabled={disabled}
            className="rounded-md border border-line bg-panel px-2 py-0.5 font-medium text-text hover:bg-panel2 disabled:opacity-60">
            {meta ? "Replace" : "Upload CSV"}
          </button>
          {meta && (
            <button onClick={onClear} className="text-muted hover:text-danger">Remove</button>
          )}
        </span>
        <input ref={input} type="file" accept=".csv,text/csv" hidden
          onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
      </div>

      {showHint && <p className="mt-1.5 text-[12px] text-muted">{hint}. Drag a file onto this bar to upload it.</p>}
      {error && <div className="mt-2"><ErrorBox>{error}</ErrorBox></div>}
    </div>
  );
}
