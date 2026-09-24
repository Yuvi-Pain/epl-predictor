import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router";
import { createQueryClient } from "./api/queryClient";
import { Layout } from "./components/Layout";
import { EmptyState } from "./components/QueryState";
import { FixturesPage } from "./pages/FixturesPage";
import { ModelPage } from "./pages/ModelPage";
import { PredictPage } from "./pages/PredictPage";
import { SeasonPage } from "./pages/SeasonPage";

/**
 * The fixtures list. The Predict page used to live at "/", so a shared link
 * like "/?home=1&away=17" is sent on to "/predict" rather than ignored.
 */
function Home() {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  if (params.has("home") || params.has("away")) {
    return <Navigate to={{ pathname: "/predict", search }} replace />;
  }
  return <FixturesPage />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="predict" element={<PredictPage />} />
        <Route path="season" element={<SeasonPage />} />
        <Route path="model" element={<ModelPage />} />
        <Route
          path="*"
          element={
            <EmptyState title="Page not found">
              <Link to="/">Back to the fixtures</Link>
            </EmptyState>
          }
        />
      </Route>
    </Routes>
  );
}

export function App() {
  const [queryClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
