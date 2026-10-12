import { describe, expect, it } from "vitest";
import { moveBy, shouldTakePlace, widgetIds } from "./order";
import type { Widget, WidgetType } from "@/lib/types";

const w = (type: WidgetType): Widget => ({ type, config: {}, expanded: false, w: 1, h: 1 });

describe("widgetIds", () => {
  it("uses the widget type, so an id survives a reorder", () => {
    const board = [w("risk_heatmap"), w("top_risk")];
    expect(widgetIds(board)).toEqual(["risk_heatmap", "top_risk"]);
    expect(widgetIds([...board].reverse())).toEqual(["top_risk", "risk_heatmap"]);
  });

  it("numbers a repeated type instead of returning a duplicate id", () => {
    expect(widgetIds([w("watchlist"), w("top_risk"), w("watchlist")])).toEqual([
      "watchlist",
      "top_risk",
      "watchlist-1",
    ]);
  });
});

describe("shouldTakePlace", () => {
  const box = (left: number, top: number, width = 500, height = 200) => ({ left, top, width, height });

  it("waits for the pointer to pass the middle of a widget in a later row", () => {
    const slot = box(0, 0);
    const below = box(0, 220);
    expect(shouldTakePlace(slot, below, { x: 100, y: 300 })).toBe(false); // upper half
    expect(shouldTakePlace(slot, below, { x: 100, y: 330 })).toBe(true); // past the middle
  });

  it("mirrors that when moving up to an earlier row", () => {
    const slot = box(0, 220);
    const above = box(0, 0);
    expect(shouldTakePlace(slot, above, { x: 100, y: 150 })).toBe(false);
    expect(shouldTakePlace(slot, above, { x: 100, y: 90 })).toBe(true);
  });

  it("compares sideways for a widget in the same row", () => {
    const slot = box(0, 0);
    const right = box(520, 0);
    expect(shouldTakePlace(slot, right, { x: 600, y: 50 })).toBe(false);
    expect(shouldTakePlace(slot, right, { x: 800, y: 50 })).toBe(true);
    expect(shouldTakePlace(right, slot, { x: 300, y: 50 })).toBe(false);
    expect(shouldTakePlace(right, slot, { x: 200, y: 50 })).toBe(true);
  });

  it("does not swap straight back after the grid reflows", () => {
    // A small widget is dragged down past the middle of a tall one. They change
    // places: the tall one moves up by the small one's height plus the gap.
    const pointer = { x: 100, y: 480 };
    const smallSlot = box(0, 0, 500, 120);
    const tall = box(0, 140, 500, 600);
    expect(shouldTakePlace(smallSlot, tall, pointer)).toBe(true);
    const tallAfter = box(0, 0, 500, 600);
    const slotAfter = box(0, 620, 500, 120);
    // The pointer is still over the tall widget, but on the slot's side of its middle.
    expect(shouldTakePlace(slotAfter, tallAfter, pointer)).toBe(false);
  });
});

describe("moveBy", () => {
  it("moves an item one place and keeps the rest in order", () => {
    expect(moveBy(["a", "b", "c"], 0, 1)).toEqual(["b", "a", "c"]);
    expect(moveBy(["a", "b", "c"], 2, -1)).toEqual(["a", "c", "b"]);
  });

  it("returns the same array at either end", () => {
    const items = ["a", "b"];
    expect(moveBy(items, 0, -1)).toBe(items);
    expect(moveBy(items, 1, 1)).toBe(items);
  });
});
