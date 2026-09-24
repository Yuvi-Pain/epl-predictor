import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { upcoming } from "../test/fixtures";
import { mockApi, renderWithProviders } from "../test/utils";
import { FixturesPage } from "./FixturesPage";

describe("FixturesPage", () => {
  it("shows the matchweek, grouped by day, soonest first", async () => {
    mockApi({ "/api/fixtures/upcoming": { body: upcoming } });
    renderWithProviders(<FixturesPage />);

    const list = await screen.findByRole("region", { name: "Fixtures" });
    expect(screen.getByText("2026-27 · Matchweek 6")).toBeInTheDocument();
    const days = within(list).getAllByRole("heading", { level: 3 });
    expect(days.map((d) => d.textContent)).toEqual(["Sat 10 Oct 2026", "Mon 12 Oct 2026"]);
    expect(within(list).getAllByRole("link")).toHaveLength(3);
  });

  it("links each fixture to the Predict page for that pairing", async () => {
    mockApi({ "/api/fixtures/upcoming": { body: upcoming } });
    renderWithProviders(<FixturesPage />);

    const link = await screen.findByRole("link", { name: /Nott'm Forest v Arsenal/ });
    expect(link).toHaveAttribute("href", "/predict?home=3&away=1");
  });

  it("shows UK kick-off times and each outcome's chance", async () => {
    mockApi({ "/api/fixtures/upcoming": { body: upcoming } });
    renderWithProviders(<FixturesPage />);

    const link = await screen.findByRole("link", { name: /Arsenal v Aston Villa/ });
    // 11:30 UTC is 12:30 in London in October (BST).
    expect(within(link).getByText("12:30")).toHaveAttribute("datetime", "2026-10-10T11:30:00Z");
    expect(link).toHaveTextContent("63%22%15%");
    // The bar's label reads the chances out for screen readers.
    expect(within(link).getByRole("img")).toHaveAccessibleName(
      "Arsenal win 63%, Draw 22%, Aston Villa win 15%. Most likely: Arsenal win.",
    );
  });

  it("says TBC when the kick-off time is not known", async () => {
    mockApi({ "/api/fixtures/upcoming": { body: upcoming } });
    renderWithProviders(<FixturesPage />);

    const link = await screen.findByRole("link", { name: /Aston Villa v Nott'm Forest/ });
    expect(link).toHaveTextContent("TBC");
  });

  it("explains an empty fixture list", async () => {
    mockApi({
      "/api/fixtures/upcoming": {
        body: { season: null, matchday: null, model_version: "v2", fixtures: [] },
      },
    });
    renderWithProviders(<FixturesPage />);

    expect(await screen.findByText("No upcoming fixtures yet")).toBeInTheDocument();
    expect(screen.getByText("FOOTBALL_DATA_API_KEY")).toBeInTheDocument();
    expect(screen.getByText("Coming up")).toBeInTheDocument();
  });

  it("shows the backend's reason when it fails", async () => {
    mockApi({
      "/api/fixtures/upcoming": { status: 503, body: { detail: "No trained model is loaded." } },
    });
    renderWithProviders(<FixturesPage />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load fixtures");
    expect(alert).toHaveTextContent("No trained model is loaded.");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
