/** Brand mark: a 3x3 matrix motif (echoing the threat x exposure grid), with the
 * top-right cell — highest threat x highest exposure — carrying the accent. */
export function Logo({ size = 26 }: { size?: number }) {
  const gap = size / 12;
  const cell = (size - gap * 2) / 3;
  const cells = [];
  for (let r = 0; r < 3; r++) {
    for (let c = 0; c < 3; c++) {
      const x = c * (cell + gap);
      const y = r * (cell + gap);
      const accent = r === 0 && c === 2;
      cells.push(
        <rect
          key={`${r}-${c}`}
          x={x}
          y={y}
          width={cell}
          height={cell}
          rx={cell * 0.22}
          fill={accent ? "var(--accent)" : "currentColor"}
          opacity={accent ? 1 : 0.28 + (2 - r) * 0.12}
        />,
      );
    }
  }
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden focusable="false">
      {cells}
    </svg>
  );
}

export function Wordmark({ size = 26 }: { size?: number }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
      <span style={{ color: "var(--text)", display: "inline-flex" }}>
        <Logo size={size} />
      </span>
      <span
        style={{
          fontWeight: 600,
          fontSize: "1.02rem",
          letterSpacing: "-0.01em",
          color: "var(--text)",
        }}
      >
        Vendor<span style={{ color: "var(--text-subtle)" }}>Risk</span>
      </span>
    </span>
  );
}
