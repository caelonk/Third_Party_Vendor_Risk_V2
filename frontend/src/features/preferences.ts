import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Preferences, Theme, Widget } from "@/lib/types";

export function usePreferences() {
  return useQuery({
    queryKey: ["preferences"],
    queryFn: () => api.get<Preferences>("/me/preferences"),
  });
}

export function useUpdatePreferences() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: { theme?: Theme; dashboard_layout?: Widget[] }) =>
      api.put<Preferences>("/me/preferences", input),
    onSuccess: (data) => qc.setQueryData(["preferences"], data),
  });
}
