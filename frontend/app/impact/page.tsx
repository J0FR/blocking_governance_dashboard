"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import AppHeader, { PageTitle } from "@/components/AppHeader";
import DatasetUpload from "@/components/impact/DatasetUpload";
import ImpactSection from "@/components/impact/ImpactSection";
import RetentionSection from "@/components/impact/RetentionSection";
import { Empty, ErrorBox, Section } from "@/components/ui";
import { impactApi, type DatasetKind } from "@/lib/api";

export default function ImpactPage() {
  const qc = useQueryClient();
  const ds = useQuery({ queryKey: ["datasets"], queryFn: impactApi.datasets });

  const refreshAll = (kind: DatasetKind) => {
    qc.invalidateQueries({ queryKey: ["datasets"] });
    qc.removeQueries({ queryKey: [kind] });
  };
  const upload = useMutation({
    mutationFn: ({ kind, file }: { kind: DatasetKind; file: File }) => impactApi.upload(kind, file),
    onSuccess: (_d, v) => refreshAll(v.kind),
  });
  const remove = useMutation({
    mutationFn: (kind: DatasetKind) => impactApi.remove(kind),
    onSuccess: (_d, kind) => refreshAll(kind),
  });

  const w = ds.data?.windows;
  const uploadingKind = upload.isPending ? upload.variables?.kind : null;
  const errorFor = (kind: DatasetKind) =>
    upload.error && upload.variables?.kind === kind ? (upload.error as Error).message : null;

  return (
    <div className="min-h-screen">
      <AppHeader>
        <nav className="flex items-center gap-4">
          <a className="hover:text-text" href="#impact">Impact</a>
          <a className="hover:text-text" href="#retention">Retention</a>
        </nav>
      </AppHeader>

      <main className="mx-auto max-w-[1400px] space-y-10 px-5 py-6">
        <PageTitle title="Block impact & retention"
          subtitle="What the blocks that were applied did to drivers, trips and supply hours, and whether drivers come back." />
        {ds.error && <ErrorBox>{(ds.error as Error).message}</ErrorBox>}

        <Section
          id="impact" title="Impact of blocks"
          subtitle="Drivers impacted, how many of them were active, and their trips and supply hours, for MX, AR, CO and the rest of SSL. The window is the 12 most recent complete weeks (Monday to Sunday)."
        >
          <div className="space-y-5">
            <DatasetUpload
              kind="impact" title="block impact result"
              hint="Columns: year_calendar_week, country_code, block_duration_type, total_impacted_drivers, active_impacted_drivers, total_finished_trips, total_supply_hours"
              windowText={w ? `${w.impact.start_date} → ${w.impact.end_date}` : "…"}
              meta={ds.data?.impact}
              uploading={uploadingKind === "impact"}
              error={errorFor("impact")}
              onFile={(file) => upload.mutate({ kind: "impact", file })}
              onClear={() => remove.mutate("impact")}
              disabled={false}
            />
            {ds.data?.impact ? <ImpactSection /> : ds.data && <Empty>Upload the block impact query result to see this section.</Empty>}
          </div>
        </Section>

        <Section
          id="retention" title="Retention after a block"
          subtitle="Do blocked drivers come back? Cohorts of blocks that ended at least 84 days ago, so all 12 retention weeks are complete."
        >
          <div className="space-y-5">
            <DatasetUpload
              kind="retention" title="retention result"
              hint="Columns: iso_year_calendar_week, country_code, retention_order, eligible_drivers_general, returned_drivers_general, eligible_drivers_active_14d, returned_drivers_active_14d"
              windowText={
                w
                  ? `data_end_date ${w.retention.data_end_date} (cohort ${w.retention.start_date} → ${w.retention.end_date})`
                  : "…"
              }
              meta={ds.data?.retention}
              uploading={uploadingKind === "retention"}
              error={errorFor("retention")}
              onFile={(file) => upload.mutate({ kind: "retention", file })}
              onClear={() => remove.mutate("retention")}
              disabled={false}
            />
            {ds.data?.retention ? <RetentionSection /> : ds.data && <Empty>Upload the retention query result to see this section.</Empty>}
          </div>
        </Section>
      </main>
    </div>
  );
}
