import { ArrowDown, ArrowUp, ArrowUpDown, Search } from "lucide-react";
import { TierBadge } from "@/components/TierBadge";
import {
  TIERS,
  isFiltered,
  type Mapping,
  type SortKey,
  type VendorFilters,
} from "@/features/vendorFilters";
import "./vendors.css";

export function VendorToolbar({
  filters,
  onChange,
  onClear,
  shown,
  total,
}: {
  filters: VendorFilters;
  onChange: (patch: Partial<VendorFilters>) => void;
  onClear: () => void;
  shown: number;
  total: number;
}) {
  const toggleTier = (t: (typeof TIERS)[number]) =>
    onChange({
      tiers: filters.tiers.includes(t) ? filters.tiers.filter((x) => x !== t) : [...filters.tiers, t],
    });

  return (
    <div className="vtool">
      <div className="vtool__row">
        <div className="vtool__search">
          <Search size={15} aria-hidden />
          <input
            className="input"
            type="search"
            aria-label="Search vendors"
            placeholder="Search by name or CPE prefix"
            value={filters.q}
            onChange={(e) => onChange({ q: e.target.value })}
          />
        </div>

        <select
          className="select vtool__select"
          aria-label="Mapping status"
          value={filters.mapping}
          onChange={(e) => onChange({ mapping: e.target.value as Mapping })}
        >
          <option value="all">All vendors</option>
          <option value="mapped">Mapped</option>
          <option value="unmapped">Unmapped</option>
        </select>

        <div className="vtool__meta">
          <span className="subtle" aria-live="polite">
            {shown === total
              ? `${total} vendor${total === 1 ? "" : "s"}`
              : `Showing ${shown} of ${total}`}
          </span>
          {isFiltered(filters) && (
            <button type="button" className="btn btn--ghost btn--sm" onClick={onClear}>
              Clear filters
            </button>
          )}
        </div>
      </div>

      <div className="vtool__chips" role="group" aria-label="Filter by tier">
        {TIERS.map((t) => (
          <button
            key={t}
            type="button"
            className="chip"
            aria-label={t}
            aria-pressed={filters.tiers.includes(t)}
            onClick={() => toggleTier(t)}
          >
            <TierBadge tier={t} />
          </button>
        ))}
        <button
          type="button"
          className="chip"
          aria-pressed={filters.kevOnly}
          onClick={() => onChange({ kevOnly: !filters.kevOnly })}
        >
          KEV only
        </button>
      </div>
    </div>
  );
}

export function SortHeader({
  label,
  sortKey,
  filters,
  onSort,
  num,
}: {
  label: string;
  sortKey: SortKey;
  filters: VendorFilters;
  onSort: (key: SortKey) => void;
  num?: boolean;
}) {
  const active = filters.sort === sortKey;
  const Icon = !active ? ArrowUpDown : filters.dir === "asc" ? ArrowUp : ArrowDown;
  return (
    <th
      className={num ? "num" : undefined}
      aria-sort={active ? (filters.dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        className={`sorth${active ? " sorth--active" : ""}`}
        onClick={() => onSort(sortKey)}
      >
        {label}
        <Icon size={12} aria-hidden />
      </button>
    </th>
  );
}
