import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { prediction, teams } from "../test/fixtures";
import { mockApi, renderWithProviders } from "../test/utils";
import { PredictPage } from "./PredictPage";

describe("PredictPage", () => {
  it("asks for two teams before predicting", async () => {
    const fetch = mockApi({ "/api/teams": { body: teams } });
    renderWithProviders(<PredictPage />);

    expect(await screen.findByLabelText("Home team")).toBeInTheDocument();
    expect(screen.getByText("Pick two teams")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("predicts once both teams are chosen", async () => {
    const user = userEvent.setup();
    const fetch = mockApi({
      "/api/teams": { body: teams },
      "/api/predict": { body: prediction },
    });
    renderWithProviders(<PredictPage />);

    await user.selectOptions(await screen.findByLabelText("Home team"), "Arsenal");
    await user.selectOptions(screen.getByLabelText("Away team"), "Aston Villa");

    const result = await screen.findByRole("region", { name: "Prediction" });
    expect(within(result).getByRole("img")).toHaveAccessibleName(/Arsenal win 56%/);
    const url = new URL(String(fetch.mock.calls.at(-1)![0]));
    expect(url.pathname).toBe("/api/predict");
    expect(url.searchParams.get("home")).toBe("1");
    expect(url.searchParams.get("away")).toBe("2");

    const drivers = screen.getByRole("region", { name: "What drove it" });
    expect(drivers).toHaveTextContent("Arsenal are rated 82 Elo points above Aston Villa.");
    // Missing form data is shown as a dash, with an explanation.
    expect(drivers).toHaveTextContent(/no earlier league matches/);
  });

  it("does not offer the home team as the away team", async () => {
    mockApi({ "/api/teams": { body: teams } });
    renderWithProviders(<PredictPage />, { route: "/predict?home=1" });

    const away = await screen.findByLabelText("Away team");
    expect(within(away).queryByRole("option", { name: "Arsenal" })).not.toBeInTheDocument();
  });

  it("swaps home and away", async () => {
    const user = userEvent.setup();
    mockApi({ "/api/teams": { body: teams }, "/api/predict": { body: prediction } });
    renderWithProviders(<PredictPage />, { route: "/predict?home=1&away=2" });

    await user.click(await screen.findByRole("button", { name: "Swap home and away" }));
    expect(screen.getByLabelText("Home team")).toHaveValue("2");
    expect(screen.getByLabelText("Away team")).toHaveValue("1");
  });

  it("shows the API's error when the model is missing", async () => {
    mockApi({
      "/api/teams": { body: teams },
      "/api/predict": { status: 503, body: { detail: "No trained model is loaded." } },
    });
    renderWithProviders(<PredictPage />, { route: "/predict?home=1&away=2" });

    expect(await screen.findByRole("alert")).toHaveTextContent("No trained model is loaded.");
  });

  it("shows an empty state when there are no teams", async () => {
    mockApi({ "/api/teams": { body: { teams: [] } } });
    renderWithProviders(<PredictPage />);
    expect(await screen.findByText("No teams yet")).toBeInTheDocument();
  });

  it("shows a loading state while teams load", () => {
    mockApi({ "/api/teams": { body: teams } });
    renderWithProviders(<PredictPage />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading teams");
  });
});
