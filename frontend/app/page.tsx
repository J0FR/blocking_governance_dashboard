"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import DriversTable from "@/components/DriversTable";
import GeoTable from "@/components/GeoTable";
import { PageTitle } from "@/components/AppHeader";
import DriverBaseBar from "@/components/DriverBaseBar";
import Header from "@/components/Header";
import Kpis from "@/components/Kpis";
import Profile from "@/components/Profile";
import UploadCard from "@/components/UploadCard";
import { Empty, ErrorBox, Section } from "@/components/ui";
import { api, type CityRow, type CountryRow, type DriverQuery } from "@/lib/api";
import { cityKey } from "@/lib/format";

/** Projection horizon is fixed: every "over N days" figure is over 180 days. */
const HORIZON_DAYS = 180;

type TableState = Pick<DriverQuery, "search" | "kind" | "sort_by" | "sort_dir" | "page" | "page_size">;
const TABLE_DEFAULT: TableState = { search: "", kind: "", sort_by: "lost_net", sort_dir: "desc", page: 0, page_size: 50 };

export default function Page() {
  const qc = useQueryClient();
  const horizon = HORIZON_DAYS;
  const [country, setCountry] = useState<string | null>(null); // filters the city table + drivers
  const [focusCity, setFocusCity] = useState<CityRow | null>(null);
  const [dq, setDq] = useState<TableState>(TABLE_DEFAULT);
  const patchTable = useCallback((p: Partial<DriverQuery>) => setDq((prev) => ({ ...prev, ...p })), []);

  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta });
  const hasSnapshot = !!meta.data?.snapshot;
  const hasList = !!meta.data?.blocklist;

  const analysis = useQuery({
    queryKey: ["analysis", horizon],
    queryFn: () => api.analysis(horizon),
    enabled: hasSnapshot && hasList,
    placeholderData: (prev) => prev,
  });

  const driverQuery: DriverQuery = {
    horizon_days: horizon,
    country: focusCity?.country_code ?? country ?? "",
    city_id: focusCity ? String(focusCity.city_id ?? "NA") : "",
    ...dq,
  };
  const drivers = useQuery({
    queryKey: ["drivers", driverQuery],
    queryFn: () => api.drivers(driverQuery),
    enabled: hasSnapshot && hasList,
    placeholderData: (prev) => prev,
  });

  const refresh = useMutation({
    mutationFn: api.refresh,
    onSuccess: () => qc.invalidateQueries(),
  });
  const uploadBase = useMutation({
    mutationFn: api.uploadSnapshot,
    onSuccess: () => {
      setCountry(null);
      setFocusCity(null);
      patchTable({ page: 0 });
      qc.invalidateQueries();
    },
  });
  const upload = useMutation({
    mutationFn: api.upload,
    onSuccess: () => {
      setCountry(null);
      setFocusCity(null);
      patchTable({ page: 0 });
      qc.invalidateQueries();
    },
  });
  const clear = useMutation({
    mutationFn: api.clearBlocklist,
    onSuccess: () => {
      setCountry(null);
      setFocusCity(null);
      qc.removeQueries({ queryKey: ["analysis"] });
      qc.removeQueries({ queryKey: ["drivers"] });
      qc.invalidateQueries({ queryKey: ["meta"] });
    },
  });

  const a = analysis.data;
  const cities = a ? (country ? a.cities.filter((c) => c.country_code === country) : a.cities) : [];
  const focusLabel = focusCity
    ? `${focusCity.city_name}, ${focusCity.country_code}`
    : country
      ? `Country ${country}`
      : null;

  const pickCountry = (r: CountryRow) => {
    setFocusCity(null);
    setCountry((c) => (c === r.country_code ? null : r.country_code));
    patchTable({ page: 0 });
  };
  const pickCity = (r: CityRow) => {
    setFocusCity((c) => (c && cityKey(c) === cityKey(r) ? null : r));
    patchTable({ page: 0 });
    document.getElementById("drivers")?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="min-h-screen">
      <Header onRefresh={() => refresh.mutate()} refreshing={refresh.isPending} />

      <main className="mx-auto max-w-[1400px] space-y-8 px-5 py-6">
        <PageTitle title="Block calculator"
          subtitle="What blocking a list of drivers costs in trips, TSH, GMV and net economic value." />
        {meta.error && <ErrorBox>{(meta.error as Error).message}</ErrorBox>}
        {refresh.error && <ErrorBox>{(refresh.error as Error).message}</ErrorBox>}

        <DriverBaseBar
          snapshot={meta.data?.snapshot}
          windowText={
            meta.data?.driver_window
              ? `${meta.data.driver_window.start_date} → ${meta.data.driver_window.end_date}`
              : "…"
          }
          uploading={uploadBase.isPending}
          error={uploadBase.error ? (uploadBase.error as Error).message : null}
          onFile={(f) => uploadBase.mutate(f)}
        />

        {meta.data && !hasSnapshot && (
          <Empty>
            There is no driver base yet. Use <b>Copy query</b> above to get the driver query with today&rsquo;s dates,
            run it on your side and upload the CSV it produces.
          </Empty>
        )}

        <UploadCard
          report={meta.data?.blocklist}
          uploading={upload.isPending}
          error={upload.error ? (upload.error as Error).message : null}
          onFile={(f) => upload.mutate(f)}
          onClear={() => clear.mutate()}
          disabled={false}
        />

        {hasSnapshot && !hasList && (
          <Empty>
            Upload a CSV with <code>driver_id</code> and <code>block_hours</code> (9999 = permanent) to see what the
            block costs in trips, TSH, GMV and economic value.
          </Empty>
        )}

        {analysis.error && <ErrorBox>{(analysis.error as Error).message}</ErrorBox>}
        {analysis.isLoading && hasList && <Empty>Calculating&hellip;</Empty>}

        {a && (
          <>
            <Section
              id="summary" title="Block summary"
              subtitle="Impact of the uploaded list, measured with each driver's activity in the previous 28 days. GMV = trips × the driver's own IPT. Economic loss = GMV − CX cost avoided (compensations + tickets × $0.69)."
            >
              <Kpis s={a.summary} />
            </Section>

            <Section
              id="countries" title="By country"
              subtitle="Click a country to filter the cities and drivers below."
            >
              <GeoTable<CountryRow>
                rows={a.countries} label="Country" horizon={horizon} maxHeight={null}
                nameOf={(r) => r.country_code} keyOf={(r) => r.country_code}
                selectedKey={country} onSelect={pickCountry}
              />
            </Section>

            <Section
              id="cities" title={country ? `Cities in ${country}` : "By city"}
              subtitle="Only cities with at least one blocked driver. Search by city name or city ID. Click a city to see its drivers."
            >
              <GeoTable<CityRow>
                rows={cities} label="City" plural="cities" horizon={horizon} searchable
                nameOf={(r) => `${r.city_name}${country ? "" : ", " + r.country_code}`}
                subOf={(r) => (r.city_id == null ? "" : String(r.city_id))}
                keyOf={(r) => cityKey(r)}
                selectedKey={focusCity ? cityKey(focusCity) : null} onSelect={pickCity}
              />
            </Section>

            <Section
              id="drivers" title="Blocked drivers"
              subtitle="Per driver: what they stop doing each week and what is lost over 180 days. Sorted by economic loss, so the drivers that matter most come first."
            >
              <DriversTable
                q={driverQuery}
                setQ={patchTable}
                data={drivers.data} loading={drivers.isFetching}
                focusLabel={focusLabel}
                onClearFocus={() => { setFocusCity(null); setCountry(null); patchTable({ page: 0 }); }}
                horizon={horizon}
              />
            </Section>

            <Section
              id="profile" title="Who gets blocked"
              subtitle="Profile of the blocked drivers compared with the whole driver base."
            >
              <Profile profile={a.profile} horizon={horizon} />
            </Section>
          </>
        )}
      </main>
    </div>
  );
}
