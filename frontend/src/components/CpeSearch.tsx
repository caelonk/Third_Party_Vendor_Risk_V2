import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useCpeSearch } from "@/features/cpe";
import "./cpe-search.css";

/**
 * Type a product name, pick a real NVD CPE product. On select, the parent gets
 * the derived `prefix` (part:vendor:product) used for CVE sync.
 */
export function CpeSearch({ onSelect }: { onSelect: (prefix: string) => void }) {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  const search = useCpeSearch(debounced);
  const results = search.data ?? [];
  const showMenu = open && debounced.length >= 2;

  const pick = (prefix: string) => {
    onSelect(prefix);
    setQ("");
    setDebounced("");
    setOpen(false);
  };

  return (
    <div className="cpe-search" ref={boxRef}>
      <div className="cpe-search__input">
        <Search size={15} className="cpe-search__icon" />
        <input
          className="input"
          placeholder="Search NVD by product name, e.g. FortiOS"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
        />
      </div>

      {showMenu && (
        <>
          <div className="cpe-search__backdrop" onClick={() => setOpen(false)} />
          <div className="cpe-search__menu">
            {search.isFetching && <div className="cpe-search__msg subtle">Searching NVD…</div>}
            {!search.isFetching && results.length === 0 && (
              <div className="cpe-search__msg subtle">No products found.</div>
            )}
            {results.map((r) => (
              <button
                key={r.prefix}
                type="button"
                className="cpe-search__item"
                onClick={() => pick(r.prefix)}
              >
                <span className="cpe-search__meta">
                  <span className="cpe-search__label">
                    {r.label}
                    {!r.active && <span className="pill cpe-search__dep">deprecated</span>}
                  </span>
                  <span className="cpe-search__prefix mono">{r.prefix}</span>
                </span>
                <span className="cpe-search__count subtle">
                  {r.version_count} version{r.version_count === 1 ? "" : "s"}
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
