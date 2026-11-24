/**
 * 分析任务服务（C1）：保存「标的 + 区间 + 对比组」，一键重跑。
 */
import { HttpClient } from "./HttpClient";
import { TaskDTO, TaskRunDTO } from "../models";

export interface CreateTaskPayload {
  name: string;
  code: string;
  days: number;
  compare_codes?: string[];
  benchmark?: string;
}

export class TaskService {
  constructor(private readonly http: HttpClient) {}

  async list(): Promise<TaskDTO[]> {
    const body = await this.http.get<{ items: TaskDTO[] }>("/tasks");
    return body.items;
  }

  async create(payload: CreateTaskPayload): Promise<TaskDTO[]> {
    const body = await this.http.post<{ items: TaskDTO[] }>("/tasks", payload);
    return body.items;
  }

  async remove(id: number): Promise<TaskDTO[]> {
    const body = await this.http.delete<{ items: TaskDTO[] }>(`/tasks/${id}`);
    return body.items;
  }

  async run(id: number): Promise<TaskRunDTO> {
    return this.http.post<TaskRunDTO>(`/tasks/${id}/run`, {});
  }
}
