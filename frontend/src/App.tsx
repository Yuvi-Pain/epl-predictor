import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router";
import { createQueryClient } from "./api/queryClient";
import { Layout } from "./components/Layout";
import { EmptyState } from "./components/QueryState";
import { ModelPage } from "./pages/ModelPage";
import { PredictPage } from "./pages/PredictPage";
import { SeasonPage } from "./pages/SeasonPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<PredictPage />} />
        <Route path="season" element={<SeasonPage />} />
        <Route path="model" element={<ModelPage />} />
        <Route
          path="*"
          element={
            <EmptyState title="Page not found">
              <Link to="/">Back to the predictor</Link>
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
