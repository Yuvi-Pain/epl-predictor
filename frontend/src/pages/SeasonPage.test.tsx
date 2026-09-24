import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { seasonRecord } from "../lib/record";
import { season } from "../test/fixtures";
import { mockApi, renderWithProviders } from "../test/utils";
import { SeasonPage } from "./SeasonPage";

describe("seasonRecord", () => {
  it("counts the running record oldest first", () => {
    const record = seasonRecord(season.matches);
    expect(record.points.map((p) => `${p.correct}/${p.played}`)).toEqual([
      "1/1",
      "1/2",
      "2/3",
      "2/4",
    ]);
    expect(record.correct).toBe(2);
    expect(record.homeWinRate).toBeCloseTo(2 / 4);
  });
});

describe("SeasonPage", () => {
  it("asks for the current season", async () => {
    const fetch = mockApi({ "/api/matches": { body: season } });
    renderWithProviders(<SeasonPage />);
    await screen.findByRole("region", { name: "Running record" });
    const url = new URL(String(fetch.mock.calls[0]![0]));
    expect(url.searchParams.get("season")).toBe("2026-27");
  });

  it("shows the record and each result, newest first", async () => {
    mockApi({ "/api/matches": { body: season } });
    renderWithProviders(<SeasonPage />);

    const record = await screen.findByRole("region", { name: "Running record" });
    expect(record).toHaveTextContent("50% of the model's top picks were right");

    const results = screen.getByRole("region", { name: "Results" });
    const days = within(results).getAllByRole("heading", { level: 3 });
    expect(days.map((d) => d.textContent)).toEqual([
      "Sat 29 Aug 2026",
      "Sat 22 Aug 2026",
      "Sat 15 Aug 2026",
    ]);

    // Newest first within a day too: the later of the two 29 Aug matches leads.
    const rows = within(results).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent?.match(/\d+\/\d+$/)?.[0])).toEqual([
      "2/4",
      "2/3",
      "1/2",
      "1/1",
    ]);
    expect(rows[0]).toHaveTextContent("Wrong");
    expect(rows[1]).toHaveTextContent("Right");
    expect(rows[2]).toHaveTextContent("Arsenal 1, Nott'm Forest 1.");
  });

  it("warns when the model trained on the season", async () => {
    mockApi({ "/api/matches": { body: { ...season, model_split: "train" } } });
    renderWithProviders(<SeasonPage />);
    expect(await screen.findByRole("note")).toHaveTextContent(/trained on this season/);
  });

  it("has an empty state before any matches", async () => {
    mockApi({ "/api/matches": { body: { ...season, matches: [] } } });
    renderWithProviders(<SeasonPage />);
    expect(await screen.findByText("No matches played yet")).toBeInTheDocument();
  });

  it("shows errors with a retry", async () => {
    mockApi({ "/api/matches": { status: 404, body: { detail: "no matches for season 2026-27" } } });
    renderWithProviders(<SeasonPage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("no matches for season 2026-27");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
