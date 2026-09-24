import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

type Route = { status?: number; body: unknown };

/**
 * Replace fetch with canned responses keyed by API path (no query string),
 * e.g. { "/api/teams": { body: {...} } }. Unknown paths answer 404.
 */
export function mockApi(routes: Record<string, Route | ((url: URL) => Route)>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = new URL(input instanceof Request ? input.url : String(input));
    const entry = routes[url.pathname];
    const route = typeof entry === "function" ? entry(url) : entry;
    const { status = 200, body } = route ?? { status: 404, body: { detail: "not mocked" } };
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
}

/** Render inside a fresh query cache (no retries) and an in-memory router. */
export function renderWithProviders(ui: ReactElement, { route = "/" } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}
