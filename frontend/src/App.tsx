import { useEffect, useState } from "react";

type Health = { status: string; postgres: string; redis: string };

type State =
  | { kind: "loading" }
  | { kind: "loaded"; httpStatus: number; health: Health }
  | { kind: "error"; message: string };

export function App() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetch("/health", { signal: controller.signal })
      .then(async (res) => {
        const health = (await res.json()) as Health;
        setState({ kind: "loaded", httpStatus: res.status, health });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ kind: "error", message: String(err) });
      });
    return () => controller.abort();
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem" }}>
      <h1>EPL Predictor</h1>
      <h2>Backend health</h2>
      {state.kind === "loading" && <p>Checking…</p>}
      {state.kind === "error" && <p role="alert">Could not reach the backend: {state.message}</p>}
      {state.kind === "loaded" && (
        <dl>
          <dt>HTTP status</dt>
          <dd>{state.httpStatus}</dd>
          <dt>Overall</dt>
          <dd>{state.health.status}</dd>
          <dt>Postgres</dt>
          <dd>{state.health.postgres}</dd>
          <dt>Redis</dt>
          <dd>{state.health.redis}</dd>
        </dl>
      )}
    </main>
  );
}
