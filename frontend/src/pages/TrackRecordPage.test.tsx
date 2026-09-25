import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { matchDay } from "../lib/format";
import { seriesOf } from "../lib/trackRecord";
import { trackRecord } from "../test/fixtures";
import { mockApi, renderWithProviders } from "../test/utils";
import { TrackRecordPage } from "./TrackRecordPage";

describe("seriesOf", () => {
  it("puts the live model first and gives each entity its own colour", () => {
    expect(seriesOf(trackRecord)).toEqual([
      { name: "v2", label: "v2 (live)", tone: "live" },
      { name: "v1", label: "v1 (shadow)", tone: "shadow" },
      { name: "bookmaker", label: "Bookmaker", tone: "bookmaker" },
    ]);
  });
});

describe("TrackRecordPage", () => {
  it("explains shadow mode and scores every predictor on the same matches", async () => {
    mockApi({ "/api/track-record": { body: trackRecord } });
    renderWithProviders(<TrackRecordPage />);

    expect(await screen.findByRole("note")).toHaveTextContent(
      "v2 is the model you see on the site. v1 runs in shadow mode",
    );
    const table = screen.getByRole("table", { name: /2 matches every model predicted/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByRole("rowheader").textContent)).toEqual([
      "v2 (live)",
      "v1 (shadow)",
      "Bookmaker",
    ]);
    expect(rows[2]).toHaveTextContent("0.950 (best)");
    const counts = screen.getAllByText(/1 postponed \(not counted until played\)/, {
      selector: "li",
    });
    expect(counts.map((li) => li.textContent?.split(":")[0])).toEqual(["v2", "v1"]);
  });

  it("draws the running log loss with a legend, direct labels and a table view", async () => {
    mockApi({ "/api/track-record": { body: trackRecord } });
    renderWithProviders(<TrackRecordPage />);

    const chart = await screen.findByRole("img", { name: /Running log loss over 2 matches/ });
    expect(chart).toHaveAccessibleName(/v2 \(live\) 1\.151, v1 \(shadow\) 1\.060, Bookmaker 0\.950/);
    expect(within(chart).getByText("Bookmaker")).toBeInTheDocument();
    expect(chart.querySelectorAll("path.chart__line")).toHaveLength(3);

    const legend = screen.getByRole("list", { name: "Lines" });
    expect(within(legend).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "v2 (live)",
      "v1 (shadow)",
      "Bookmaker",
    ]);

    const byDate = screen.getByRole("region", { name: "Running log loss by date" });
    expect(within(byDate).getAllByRole("row")[1]).toHaveTextContent(`${matchDay("2026-09-19")}10.6930.9160.730`);
  });

  it("reads out a date's values from the keyboard", async () => {
    mockApi({ "/api/track-record": { body: trackRecord } });
    renderWithProviders(<TrackRecordPage />);

    const chart = await screen.findByRole("img", { name: /Running log loss/ });
    fireEvent.focus(chart);
    fireEvent.keyDown(chart, { key: "Home" });
    expect(screen.getByText(`${matchDay("2026-09-19")} · 1 match`)).toBeInTheDocument();
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(screen.getByText(`${matchDay("2026-09-20")} · 2 matches`)).toBeInTheDocument();
  });

  it("lists each match with every model's frozen pick and how it did", async () => {
    mockApi({ "/api/track-record": { body: trackRecord } });
    renderWithProviders(<TrackRecordPage />);

    const list = await screen.findByRole("region", { name: "Predictions v results" });
    const days = within(list).getAllByRole("heading", { level: 3 });
    expect(days.map((d) => d.textContent)).toEqual(
      ["2026-09-27", "2026-09-21", "2026-09-20", "2026-09-19"].map(matchDay),
    );

    const postponed = within(list).getByRole("region", { name: matchDay("2026-09-21") });
    expect(within(postponed).getAllByText("Postponed: not counted until played")).toHaveLength(2);

    const played = within(list).getByRole("region", { name: matchDay("2026-09-19") });
    expect(played).toHaveTextContent("Arsenal 2, Aston Villa 0.");
    const picks = within(played).getAllByRole("listitem").slice(1);
    expect(picks[0]).toHaveTextContent(/v2 \(live\)Arsenal win \(50%\).*Right/);
    expect(picks[2]).toHaveTextContent("BookmakerArsenal win (52%)");

    const pending = within(list).getByRole("region", { name: matchDay("2026-09-27") });
    expect(within(pending).getAllByText("Awaiting result")).toHaveLength(2);
    expect(pending).toHaveTextContent("Kick-off 14:00");
  });

  it("says so when nothing has been saved yet", async () => {
    mockApi({
      "/api/track-record": {
        body: {
          ...trackRecord,
          season: null,
          models: [],
          compared_matches: 0,
          scores: [],
          running: [],
          matches: [],
        },
      },
    });
    renderWithProviders(<TrackRecordPage />);
    expect(await screen.findByText("No predictions saved yet")).toBeInTheDocument();
  });

  it("shows the error from the backend", async () => {
    mockApi({ "/api/track-record": { status: 500, body: { detail: "database is down" } } });
    renderWithProviders(<TrackRecordPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("database is down");
  });
});
