import type { TaskDTO } from "../api/types";

/** Status plus the run outcome when it differs (a PARTIAL answer or a run interrupted by a restart). */
export function taskStatusLabel(task: TaskDTO): string {
  return task.outcome && task.outcome !== task.status ? `${task.status} · ${task.outcome}` : task.status;
}
