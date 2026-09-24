import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "./App";
import { modelInfo, teams } from "./test/fixtures";
import { mockApi, renderWithProviders } from "./test/utils";

describe("App routes", () => {
  it("navigates between pages with the main nav", async () => {
    const user = userEvent.setup();
    mockApi({ "/api/teams": { body: teams }, "/api/model": { body: modelInfo } });
    renderWithProviders(<AppRoutes />);

    expect(screen.getByRole("heading", { level: 1, name: "Who wins?" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(screen.getByRole("link", { name: "Predict" })).toHaveAttribute("aria-current", "page");

    await user.click(within(nav).getByRole("link", { name: "Model" }));
    expect(screen.getByRole("heading", { level: 1, name: "The model" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Version v1" })).toBeInTheDocument();
  });

  it("has a not-found page", () => {
    mockApi({});
    renderWithProviders(<AppRoutes />, { route: "/nope" });
    expect(screen.getByText("Page not found")).toBeInTheDocument();
  });
});
