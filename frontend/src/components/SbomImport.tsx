import { Fragment, useRef, useState, type DragEvent } from "react";
import { FileJson, Info, Upload } from "lucide-react";
import {
  defaultSelection,
  isImportable,
  readSbomFile,
  selectAll,
  summarize,
  toImportItems,
  useSbomImport,
  useSbomPreview,
} from "@/features/sbom";
import type { SbomCandidate, SbomImportResult, SbomPreview } from "@/lib/types";
import "./sbom-import.css";

const FORMAT_LABEL = { cyclonedx: "CycloneDX", spdx: "SPDX" } as const;
const STATUS_LABEL: Record<SbomCandidate["status"], string> = {
  new: "New",
  exists: "Already added",
  duplicate: "Duplicate in file",
};
const SKIP_LABEL = { exists: "already added", invalid_cpe: "invalid CPE", empty_name: "no name" };

/** A CPE prefix that may wrap only after its colons (<wbr> leaves copied text intact). */
function CpeText({ value }: { value: string }) {
  return (
    <span className="mono sbom__cpe">
      {value.split(":").map((part, i) => (
        <Fragment key={i}>
          {i > 0 && (
            <>
              :<wbr />
            </>
          )}
          {part}
        </Fragment>
      ))}
    </span>
  );
}

function Versions({ versions }: { versions: string[] }) {
  if (versions.length === 0) return <span className="subtle">—</span>;
  const shown = versions.slice(0, 3).join(", ");
  return (
    <span className="mono" title={versions.join(", ")}>
      {shown}
      {versions.length > 3 && <span className="subtle"> +{versions.length - 3}</span>}
    </span>
  );
}

export function SbomImport({ onDone }: { onDone: () => void }) {
  const preview = useSbomPreview();
  const doImport = useSbomImport();
  const inputRef = useRef<HTMLInputElement>(null);

  const [step, setStep] = useState<"pick" | "review" | "done">("pick");
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [data, setData] = useState<SbomPreview | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [result, setResult] = useState<{ res: SbomImportResult; mapped: number } | null>(null);

  const readFile = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    try {
      const doc = await readSbomFile(file);
      const p = await preview.mutateAsync(doc);
      setData(p);
      setSelected(defaultSelection(p.candidates));
      setStep("review");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read that SBOM.");
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    void readFile(e.dataTransfer.files[0]);
  };

  const toggle = (i: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });

  const submit = () => {
    if (!data) return;
    const items = toImportItems(data.candidates, selected);
    setError(null);
    doImport.mutate(items, {
      onSuccess: (res) => {
        const created = new Set(res.names);
        const mapped = items.filter((it) => created.has(it.name) && it.cpe_prefix).length;
        setResult({ res, mapped });
        setStep("done");
      },
      onError: (e) => setError(e instanceof Error ? e.message : "Import failed."),
    });
  };

  // ---------------------------------------------------------------- step 1 --
  if (step === "pick") {
    return (
      <div className="sbom">
        {error && <div className="banner banner--error">{error}</div>}
        <div
          className={`sbom__drop${dragging ? " sbom__drop--over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          {preview.isPending ? (
            <>
              <span className="spinner" />
              <p className="subtle">Reading SBOM…</p>
            </>
          ) : (
            <>
              <FileJson size={28} className="sbom__drop-icon" aria-hidden />
              <p>
                <strong>Drop an SBOM file here</strong>
                <span className="subtle"> or </span>
              </p>
              <button type="button" className="btn btn--secondary" onClick={() => inputRef.current?.click()}>
                <Upload size={16} /> Choose file
              </button>
              <input
                ref={inputRef}
                type="file"
                accept=".json,application/json"
                hidden
                onChange={(e) => {
                  void readFile(e.target.files?.[0]);
                  e.target.value = ""; // allow re-choosing the same file
                }}
              />
            </>
          )}
        </div>
        <p className="subtle sbom__hint">
          CycloneDX JSON or SPDX 2.x JSON, up to 10 MB. Nothing is saved until you review and
          confirm the import.
        </p>
      </div>
    );
  }

  // ---------------------------------------------------------------- step 3 --
  if (step === "done" && result) {
    const { res, mapped } = result;
    const unmapped = res.created - mapped;
    return (
      <div className="sbom">
        <div className="banner banner--ok">
          Imported {res.created} vendor{res.created === 1 ? "" : "s"}.
        </div>
        <ul className="sbom__outcome">
          {mapped > 0 && (
            <li>
              {mapped} with a CPE mapping will be scored at the next automatic sync — or open one
              and sync it now.
            </li>
          )}
          {unmapped > 0 && (
            <li>
              {unmapped} without a mapping will show as Not Assessed until you edit{" "}
              {unmapped === 1 ? "it" : "them"} and pick an NVD product.
            </li>
          )}
          {res.skipped.length > 0 && (
            <li>
              Skipped {res.skipped.length}:{" "}
              {res.skipped.map((s) => `${s.name} (${SKIP_LABEL[s.reason]})`).join(", ")}.
            </li>
          )}
        </ul>
        <div className="sbom__footer">
          <span />
          <button type="button" className="btn btn--primary" onClick={onDone}>
            Done
          </button>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------- step 2 --
  if (!data) return null;
  const counts = summarize(data.candidates, selected);
  const importable = data.candidates.filter(isImportable).length;

  return (
    <div className="sbom">
      {error && <div className="banner banner--error">{error}</div>}

      <div className="sbom__summary">
        <span className="pill">
          {FORMAT_LABEL[data.format]}
          {data.spec_version ? ` ${data.spec_version}` : ""}
        </span>
        {data.subject && <span className="subtle">for {data.subject}</span>}
        <span className="subtle">
          · {data.component_count} component{data.component_count === 1 ? "" : "s"} →{" "}
          {data.candidates.length} product{data.candidates.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className="banner sbom__note">
        <Info size={16} aria-hidden />
        <span>
          Risk is scored per product across all of its published versions. The versions below
          come from your SBOM for reference — they don't narrow CVE matching.
        </span>
      </div>

      <div className="sbom__controls">
        <span className="subtle">Select:</span>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => setSelected(selectAll(data.candidates, true))}>
          Mapped
        </button>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => setSelected(selectAll(data.candidates, false))}>
          All new
        </button>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => setSelected(new Set())}>
          None
        </button>
        <span className="subtle sbom__count" aria-live="polite">
          {counts.total} of {importable} selected · {counts.mapped} mapped, {counts.unmapped} unmapped
        </span>
      </div>

      <div className="sbom__table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th aria-label="Select" />
              <th>Product</th>
              <th>CPE mapping</th>
              <th>Versions</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.candidates.map((c, i) => {
              const can = isImportable(c);
              const id = `sbom-row-${i}`;
              return (
                <tr key={i} className={can ? undefined : "sbom__row--off"}>
                  <td>
                    <input
                      id={id}
                      type="checkbox"
                      checked={selected.has(i)}
                      disabled={!can}
                      onChange={() => toggle(i)}
                    />
                  </td>
                  <td>
                    <label htmlFor={id} className="sbom__name">
                      {c.name}
                    </label>
                    {c.supplier && <div className="subtle sbom__supplier">{c.supplier}</div>}
                  </td>
                  <td>
                    {c.cpe_prefix ? (
                      <CpeText value={c.cpe_prefix} />
                    ) : (
                      <span className="subtle">No CPE — imports as Not Assessed</span>
                    )}
                  </td>
                  <td>
                    <Versions versions={c.versions} />
                  </td>
                  <td>
                    <span className={`pill sbom__status sbom__status--${c.status}`}>
                      {STATUS_LABEL[c.status]}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="sbom__footer">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => {
            setStep("pick");
            setData(null);
            setError(null);
          }}
        >
          Choose a different file
        </button>
        <button
          type="button"
          className="btn btn--primary"
          disabled={counts.total === 0 || doImport.isPending}
          onClick={submit}
        >
          {doImport.isPending ? (
            <span className="spinner" style={{ width: 14, height: 14 }} />
          ) : (
            `Import ${counts.total} vendor${counts.total === 1 ? "" : "s"}`
          )}
        </button>
      </div>
    </div>
  );
}
