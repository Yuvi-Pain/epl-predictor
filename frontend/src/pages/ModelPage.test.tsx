import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { modelInfo } from "../test/fixtures";
import { mockApi, renderWithProviders } from "../test/utils";
import { ModelPage } from "./ModelPage";
import { bookmakerVerdict } from "./model/VersusBookmaker";

describe("bookmakerVerdict", () => {
  it("says who was better on log loss", () => {
    expect(bookmakerVerdict(modelInfo.test)).toMatch(/bookmaker's odds were better calibrated.*0\.022/);
    const better = { ...modelInfo.test, model: { ...modelInfo.test.model, log_loss: 0.95 } };
    expect(bookmakerVerdict(better)).toMatch(/model beat the bookmaker on log loss by 0\.032/);
  });

  it("is null without a bookmaker baseline", () => {
    expect(bookmakerVerdict(modelInfo.validation)).toBeNull();
  });
});

describe("ModelPage", () => {
  it("shows version, test metrics and the best score in each column", async () => {
    mockApi({ "/api/model": { body: modelInfo } });
    renderWithProviders(<ModelPage />);

    expect(await screen.findByRole("heading", { name: "Version v1" })).toBeInTheDocument();
    expect(screen.getByText("2015-16 – 2023-24")).toBeInTheDocument();

    const table = screen.getByRole("table", { name: /2025-26: held back/ });
    const bookie = within(table).getByRole("row", { name: /Bookmaker \(Bet365\)/ });
    expect(bookie).toHaveTextContent("53.0% (best)");
    expect(bookie).toHaveTextContent("0.982 (best)");
    const model = within(table).getByRole("row", { name: /This model/ });
    expect(model).toHaveTextContent("51.0%");
    expect(model).not.toHaveTextContent("(best)");
  });

  it("explains a missing model", async () => {
    mockApi({ "/api/model": { status: 503, body: { detail: "No trained model is loaded." } } });
    renderWithProviders(<ModelPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No trained model is loaded.");
  });
});
