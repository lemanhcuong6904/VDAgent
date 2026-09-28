import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";
import { ApiClient, ApiError } from "./client";
import { queryKeys } from "./keys";

export const ApiContext = createContext<ApiClient>(new ApiClient(null));

export function useApi(): ApiClient {
  return useContext(ApiContext);
}

export const MESSAGE_PAGE_SIZE = 50;

export function useUsers() {
  const api = useApi();
  return useQuery({ queryKey: queryKeys.users, queryFn: () => api.listUsers() });
}

export function useAgents() {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.agents,
    queryFn: () => api.listAgents(),
    refetchInterval: 10_000,
  });
}

/** Newest page first; `fetchNextPage` loads the next older page via `before_seq`. */
export function useMessages(agent: string) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: queryKeys.messages(agent),
    queryFn: ({ pageParam }) => api.getMessages(agent, pageParam, MESSAGE_PAGE_SIZE),
    initialPageParam: null as number | null,
    // Seqs are contiguous from 1 per stack, so anything older exists iff the oldest seq > 1.
    getNextPageParam: (oldest) => {
      const first = oldest.messages[0];
      return first && first.seq > 1 ? first.seq : undefined;
    },
    refetchInterval: 5_000,
  });
}

export function useTasks() {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.tasks,
    queryFn: () => api.listTasks(),
    refetchInterval: 5_000,
  });
}

export function useTask(id: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.task(id ?? ""),
    queryFn: () => api.getTask(id as string),
    enabled: id !== null,
    refetchInterval: (query) => (query.state.data?.task.status === "running" ? 3_000 : false),
  });
}

export function useDataset(id: string, offset: number, limit: number) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.dataset(id, offset, limit),
    queryFn: () => api.getDataset(id, offset, limit),
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
}

export function useChart(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.chart(id),
    queryFn: () => api.getChart(id),
    staleTime: Infinity,
  });
}

export function useReports() {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.reports,
    queryFn: () => api.listReports(),
    refetchInterval: 5_000,
  });
}

export function useReport(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.report(id),
    queryFn: () => api.getReport(id),
    staleTime: Infinity,
  });
}

/** A 404 is an answer ("no run for this task"), not a transient failure worth retrying. */
function retryUnlessNotFound(failureCount: number, error: Error): boolean {
  return !(error instanceof ApiError && error.status === 404) && failureCount < 3;
}

export function useTaskRun(taskId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.taskRun(taskId ?? ""),
    queryFn: () => api.getTaskRun(taskId as string),
    enabled: taskId !== null,
    staleTime: Infinity,
    retry: retryUnlessNotFound,
  });
}

export function useRunView(runId: string | null) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.runView(runId ?? ""),
    queryFn: () => api.getRunView(runId as string),
    enabled: runId !== null,
    retry: retryUnlessNotFound,
    refetchInterval: (query) =>
      query.state.data && !query.state.data.run.terminal ? 3_000 : false,
  });
}
