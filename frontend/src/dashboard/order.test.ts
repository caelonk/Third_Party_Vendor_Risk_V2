import { describe, expect, it } from "vitest";
import { widgetIds } from "./order";
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
