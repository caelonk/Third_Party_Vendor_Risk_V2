import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (count, err) => {
        // Never retry auth/permission/not-found — only transient failures.
        if (err instanceof ApiError && err.status < 500) return false;
        return count < 2;
      },
      refetchOnWindowFocus: false,
    },
  },
});
