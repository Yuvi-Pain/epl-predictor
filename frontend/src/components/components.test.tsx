import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { teamHue, teamInitials } from "../lib/teams";
import { ProbabilityBar } from "./ProbabilityBar";
import { ErrorState } from "./QueryState";
import { ApiError } from "../api/client";
import { TeamName } from "./TeamBadge";
import { ThemeToggle } from "./ThemeToggle";

describe("ProbabilityBar", () => {
  const props = {
    probabilities: { home_win: 0.56, draw: 0.24, away_win: 0.2 },
    home: "Arsenal",
    away: "Aston Villa",
    mostLikely: "home_win" as const,
  };

  it("describes all three outcomes for screen readers", () => {
    render(<ProbabilityBar {...props} />);
    expect(
      screen.getByRole("img", {
        name: "Arsenal win 56%, Draw 24%, Aston Villa win 20%. Most likely: Arsenal win.",
      }),
    ).toBeInTheDocument();
  });

  it("shows the numbers and flags the most likely outcome in text", () => {
    render(<ProbabilityBar {...props} />);
    expect(screen.getByText("56%")).toBeInTheDocument();
    expect(screen.getByText(/Arsenal win · most likely/)).toBeInTheDocument();
  });

  it("sizes segments by probability", () => {
    const { container } = render(<ProbabilityBar {...props} />);
    const draw = container.querySelector(".probability__segment--draw") as HTMLElement;
    expect(draw.style.flexGrow).toBe("0.24");
  });

  it("drops the legend when compact", () => {
    render(<ProbabilityBar {...props} compact />);
    expect(screen.queryByText("56%")).not.toBeInTheDocument();
    expect(screen.getByRole("img")).toBeInTheDocument();
  });
});

describe("team badges", () => {
  it.each([
    ["Arsenal", "ARS"],
    ["Aston Villa", "AV"],
    ["Nott'm Forest", "NF"],
    ["Brighton and Hove Albion", "BH"],
  ])("%s -> %s", (name, initials) => {
    expect(teamInitials(name)).toBe(initials);
  });

  it("gives a team the same hue every time", () => {
    expect(teamHue("Everton")).toBe(teamHue("Everton"));
    expect(teamHue("Everton")).toBeGreaterThanOrEqual(0);
    expect(teamHue("Everton")).toBeLessThan(360);
  });

  it("hides the badge from assistive tech and keeps the name", () => {
    render(<TeamName name="Aston Villa" />);
    expect(screen.getByText("AV")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByText("Aston Villa")).toBeVisible();
  });
});

describe("ErrorState", () => {
  it("shows the backend's own error detail", () => {
    render(<ErrorState title="Oops" error={new ApiError(503, "No trained model is loaded.")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("No trained model is loaded.");
  });

  it("explains network failures", () => {
    render(<ErrorState title="Oops" error={new TypeError("Failed to fetch")} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/Is the backend running/);
  });
});

describe("ThemeToggle", () => {
  it("applies and remembers the chosen theme", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    await user.click(screen.getByRole("button", { name: "Dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(screen.getByRole("button", { name: "Dark theme" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "Match system theme" }));
    expect(document.documentElement).not.toHaveAttribute("data-theme");
    expect(localStorage.getItem("theme")).toBeNull();
  });
});
