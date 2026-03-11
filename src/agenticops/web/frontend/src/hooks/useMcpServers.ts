import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { McpServerConfig, McpServersMap } from "@/api/types";

const KEY = ["mcp-servers"];

export function useMcpServers() {
  return useQuery<McpServersMap>({
    queryKey: KEY,
    queryFn: () => apiFetch("/api/settings/mcp-servers"),
  });
}

export function useUpsertMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, config }: { name: string; config: McpServerConfig }) =>
      apiFetch(`/api/settings/mcp-servers/${encodeURIComponent(name)}`, {
        method: "PUT",
        body: JSON.stringify(config),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDeleteMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch(`/api/settings/mcp-servers/${encodeURIComponent(name)}`, {
        method: "DELETE",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useImportMcpServers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { mcpServers: Record<string, McpServerConfig> }) =>
      apiFetch<{ imported: string[]; count: number }>(
        "/api/settings/mcp-servers/import",
        { method: "POST", body: JSON.stringify(data) },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useReloadMcpServers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch("/api/settings/mcp-servers/reload", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
