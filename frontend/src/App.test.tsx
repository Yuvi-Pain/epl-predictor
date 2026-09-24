import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "./App";
import { modelInfo, prediction, teams, upcoming } from "./test/fixtures";
import { mockApi, renderWithProviders } from "./test/utils";

describe("App routes", () => {
  it("opens on the upcoming fixtures and navigates with the main nav", async () => {
    const user = userEvent.setup();
    mockApi({
      "/api/fixtures/upcoming": { body: upcoming },
      "/api/teams": { body: teams },
      "/api/model": { body: modelInfo },
    });
    renderWithProviders(<AppRoutes />);

    expect(screen.getByRole("heading", { level: 1, name: "Next up" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Fixtures" })).toHaveAttribute(
      "aria-current",
      "page",
    );

    await user.click(within(nav).getByRole("link", { name: "Predict" }));
    expect(screen.getByRole("heading", { level: 1, name: "Who wins?" })).toBeInTheDocument();

    await user.click(within(nav).getByRole("link", { name: "Model" }));
    expect(screen.getByRole("heading", { level: 1, name: "The model" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Version v1" })).toBeInTheDocument();
  });

  it("opens the prediction for a fixture when it is clicked", async () => {
    const user = userEvent.setup();
    const fetch = mockApi({
      "/api/fixtures/upcoming": { body: upcoming },
      "/api/teams": { body: teams },
      "/api/predict": { body: prediction },
    });
    renderWithProviders(<AppRoutes />);

    await user.click(await screen.findByRole("link", { name: /Arsenal v Aston Villa/ }));
    expect(screen.getByRole("heading", { level: 1, name: "Who wins?" })).toBeInTheDocument();
    expect(await screen.findByText("56%")).toBeInTheDocument();

    const predictCall = fetch.mock.calls
      .map(([input]) => new URL(String(input)))
      .find((url) => url.pathname === "/api/predict");
    expect(predictCall?.searchParams.get("home")).toBe("1");
    expect(predictCall?.searchParams.get("away")).toBe("2");
  });

  it("sends old Predict links from / on to /predict", async () => {
    mockApi({ "/api/teams": { body: teams }, "/api/predict": { body: prediction } });
    renderWithProviders(<AppRoutes />, { route: "/?home=1&away=2" });

    expect(screen.getByRole("heading", { level: 1, name: "Who wins?" })).toBeInTheDocument();
    expect(await screen.findByText("56%")).toBeInTheDocument();
  });

  it("has a not-found page", () => {
    mockApi({});
    renderWithProviders(<AppRoutes />, { route: "/nope" });
    expect(screen.getByText("Page not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the fixtures" })).toHaveAttribute("href", "/");
  });
});
