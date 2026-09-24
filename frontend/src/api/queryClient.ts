import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./client";

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // A 4xx will not fix itself (unknown team, no such season), and a 503
        // means no model is loaded, so only retry network and 5xx errors.
        retry: (failureCount, error) => {
          if (error instanceof ApiError && (error.status < 500 || error.status === 503)) {
            return false;
          }
          return failureCount < 2;
        },
        refetchOnWindowFocus: false,
      },
    },
  });
}
