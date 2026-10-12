import { describe, expect, it } from "vitest";
import {
  STICKINESS,
  layoutBoard,
  nudge,
  pickPlacement,
  shorterColumn,
  withColumns,
  type BoardMetrics,
} from "./layout";
import { widgetIds } from "./order";
import type { Widget, WidgetType } from "@/lib/types";

const w = (type: WidgetType, col?: 0 | 1, expanded = false): Widget => ({
  type,
  config: {},
  expanded,
  col,
  w: expanded ? 2 : 1,
  h: 1,
});

// The board in the bug report: a short widget beside a tall one in each row.
const kev = w("kev_exposure", 0);
const heat = w("risk_heatmap", 1);
const renewal = w("watchlist", 0);
const trend = w("cve_trend", 1);
const tiers = w("tier_distribution", 0);
const board = [kev, heat, renewal, trend, tiers];
const HEIGHTS = {
  kev_exposure: 130,
  risk_heatmap: 420,
  watchlist: 110,
  cve_trend: 190,
  tier_distribution: 140,
  top_risk: 220,
};
const GAP = 24;
const WIDTH = 1024; // two 500px columns
const metrics = (columns: 1 | 2 = 2): BoardMetrics => ({ heights: HEIGHTS, gap: GAP, columns });
const types = (list: Widget[]) => list.map((x) => `${x.type}:${x.expanded ? "full" : x.col}`);

describe("layoutBoard", () => {
  it("packs each column tightly, so a short widget leaves no hole beside a tall one", () => {
    const { tops, height } = layoutBoard(board, widgetIds(board), metrics());
    expect(tops).toEqual({
      kev_exposure: 0,
      watchlist: 130 + GAP, // directly under KEV, not level with the bottom of the heatmap
      tier_distribution: 130 + GAP + 110 + GAP,
      risk_heatmap: 0,
      cve_trend: 420 + GAP,
    });
    expect(height).toBe(420 + GAP + 190); // the taller (right) column
  });

  it("starts an expanded widget below both columns, and everything after it below that", () => {
    const list = [kev, heat, w("top_risk", 0, true), renewal, trend];
    const { tops } = layoutBoard(list, widgetIds(list), metrics());
    expect(tops.top_risk).toBe(420 + GAP);
    expect(tops.watchlist).toBe(420 + GAP + 220 + GAP);
    expect(tops.cve_trend).toBe(tops.watchlist); // both columns restart level
  });

  it("stacks everything in list order on a narrow screen", () => {
    const { tops, height } = layoutBoard(board, widgetIds(board), metrics(1));
    expect(Object.entries(tops).sort((a, b) => a[1] - b[1]).map(([id]) => id)).toEqual(
      widgetIds(board),
    );
    expect(height).toBe(130 + 420 + 110 + 190 + 140 + 4 * GAP);
  });

  it("is empty for an empty board", () => {
    expect(layoutBoard([], [], metrics())).toEqual({ tops: {}, height: 0 });
  });
});

describe("withColumns", () => {
  it("keeps a layout saved before columns on the sides it was on", () => {
    const old = [w("kev_exposure"), w("risk_heatmap"), w("watchlist"), w("cve_trend")];
    expect(withColumns(old).map((x) => x.col)).toEqual([0, 1, 0, 1]);
  });

  it("restarts on the left after an expanded widget, as the old rows did", () => {
    const old = [w("kev_exposure"), w("top_risk", undefined, true), w("watchlist"), w("cve_trend")];
    expect(withColumns(old).map((x) => x.col)).toEqual([0, undefined, 0, 1]);
  });

  it("leaves saved columns alone, and treats null as unset", () => {
    const saved = [w("kev_exposure", 1), { ...w("watchlist"), col: null }, w("cve_trend", 1)];
    expect(withColumns(saved).map((x) => x.col)).toEqual([1, 1, 1]);
  });
});

describe("shorterColumn", () => {
  it("picks the side whose content ends higher", () => {
    expect(shorterColumn(board, widgetIds(board), metrics())).toBe(0); // 428 vs 634
    const leftHeavy = [kev, renewal, tiers, w("top_risk", 0)];
    expect(shorterColumn(leftHeavy, widgetIds(leftHeavy), metrics())).toBe(1);
    expect(shorterColumn([], [], metrics())).toBe(0);
  });
});

describe("pickPlacement", () => {
  const place = (list: Widget[], type: WidgetType, point: { x: number; y: number }, columns: 1 | 2 = 2) => {
    const ids = widgetIds(list);
    return pickPlacement(list, ids, ids.indexOf(type), point, metrics(columns), WIDTH);
  };
  const RIGHT = (WIDTH + GAP) / 2; // left edge of the right column

  it("stays put while the card is near its own slot", () => {
    expect(place(board, "cve_trend", { x: RIGHT, y: 420 + GAP })).toBeNull();
    expect(place(board, "cve_trend", { x: RIGHT - 30, y: 420 + GAP + 20 })).toBeNull();
  });

  it("drops a widget into the free space at the bottom of the other column", () => {
    // CVE trend dragged from under the heatmap to the empty area under Tier distribution.
    const next = place(board, "cve_trend", { x: 0, y: 428 });
    expect(types(next!.widgets)).toEqual([
      "kev_exposure:0",
      "risk_heatmap:1",
      "watchlist:0",
      "tier_distribution:0",
      "cve_trend:0",
    ]);
  });

  it("inserts between two widgets of the other column", () => {
    // Held level with the gap between KEV and Renewal watchlist, on the left.
    const next = place(board, "cve_trend", { x: 10, y: 150 });
    const { tops } = layoutBoard(next!.widgets, next!.ids, metrics());
    expect(tops.cve_trend).toBe(130 + GAP);
    expect(tops.watchlist).toBe(130 + GAP + 190 + GAP); // pushed down to make room
    expect(next!.widgets.find((x) => x.type === "cve_trend")!.col).toBe(0);
  });

  it("moves within a column once the card is nearer the other position", () => {
    // Tier distribution (bottom left) lifted to the top of the left column.
    const next = place(board, "tier_distribution", { x: 0, y: 5 });
    expect(types(next!.widgets).filter((t) => t.endsWith(":0"))).toEqual([
      "tier_distribution:0",
      "kev_exposure:0",
      "watchlist:0",
    ]);
  });

  it("gives the same answer wherever the slot currently is, so it cannot flip-flop", () => {
    const point = { x: 12, y: 300 };
    const first = place(board, "cve_trend", point)!;
    // Asked again from the new arrangement with the card in the same place: no further move.
    expect(pickPlacement(first.widgets, first.ids, first.ids.indexOf("cve_trend"), point, metrics(), WIDTH)).toBeNull();
  });

  it("does not switch for a difference smaller than the stickiness", () => {
    // Midway between "under KEV" (top 154) and "under Renewal" (top 288) on the left.
    const underKev = place(board, "cve_trend", { x: 0, y: 160 })!;
    const idx = underKev.ids.indexOf("cve_trend");
    const midpoint = (154 + 288) / 2;
    const nudgeOver = { x: 0, y: midpoint + STICKINESS / 2 - 1 };
    expect(pickPlacement(underKev.widgets, underKev.ids, idx, nudgeOver, metrics(), WIDTH)).toBeNull();
    const wellOver = { x: 0, y: midpoint + STICKINESS };
    expect(pickPlacement(underKev.widgets, underKev.ids, idx, wellOver, metrics(), WIDTH)).not.toBeNull();
  });

  it("moves an expanded widget as a full row, keeping its width", () => {
    const list = [kev, heat, w("top_risk", 0, true), renewal, trend];
    const next = place(list, "top_risk", { x: 0, y: 0 })!;
    expect(types(next.widgets)[0]).toBe("top_risk:full");
    expect(layoutBoard(next.widgets, next.ids, metrics()).tops.kev_exposure).toBe(220 + GAP);
  });

  it("only reorders on a narrow screen, leaving the saved columns alone", () => {
    const next = place(board, "tier_distribution", { x: 0, y: 0 }, 1)!;
    expect(next.widgets[0].type).toBe("tier_distribution");
    expect(next.widgets.map((x) => x.col).sort()).toEqual([0, 0, 0, 1, 1]);
  });
});

describe("nudge", () => {
  it("moves past the neighbour in the same column, skipping the other column", () => {
    const up = nudge(board, 4, "up", 2); // Tier distribution, left column
    expect(types(up).filter((t) => t.endsWith(":0"))).toEqual([
      "kev_exposure:0",
      "tier_distribution:0",
      "watchlist:0",
    ]);
    const down = nudge(board, 0, "down", 2);
    expect(types(down).filter((t) => t.endsWith(":0"))).toEqual([
      "watchlist:0",
      "kev_exposure:0",
      "tier_distribution:0",
    ]);
  });

  it("switches column with left and right", () => {
    const right = nudge(board, 4, "right", 2);
    expect(right[4]).toMatchObject({ type: "tier_distribution", col: 1 });
    expect(nudge(right, 4, "left", 2)[4].col).toBe(0);
  });

  it("returns the same array when there is nowhere to go", () => {
    expect(nudge(board, 0, "up", 2)).toBe(board);
    expect(nudge(board, 4, "down", 2)).toBe(board);
    expect(nudge(board, 0, "left", 2)).toBe(board); // already on the left
    expect(nudge(board, 0, "right", 1)).toBe(board); // one column: no sides
    const full = [w("top_risk", 0, true), kev];
    expect(nudge(full, 0, "right", 2)).toBe(full); // an expanded widget has no side
  });

  it("moves an expanded widget past either column's neighbour", () => {
    const list = [kev, heat, w("top_risk", 0, true)];
    expect(nudge(list, 2, "up", 2).map((x) => x.type)).toEqual([
      "kev_exposure",
      "top_risk",
      "risk_heatmap",
    ]);
  });
});
