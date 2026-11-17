/**
 * 追问服务（C2）：把「问什么」与「后端怎么答」隔离开。
 *
 * 组件只拿到 ChatAnswerDTO，不需要知道背后是 LLM 还是模板、
 * 也不需要知道动作是服务端执行还是前端执行。
 */
import { HttpClient } from "./HttpClient";
import { ChatAnswerDTO, ChatMessage } from "../models";

export interface AskPayload {
  question: string;
  code: string;
  start?: string;
  end?: string;
  event?: Record<string, unknown> | null;
  report_id?: number;
  history?: ChatMessage[];
}

export class ChatService {
  constructor(private readonly http: HttpClient) {}

  async ask(payload: AskPayload): Promise<ChatAnswerDTO> {
    const history = (payload.history ?? [])
      .slice(-6)
      .map((m) => ({ role: m.role, content: m.content }));
    return this.http.post<ChatAnswerDTO>("/chat", { ...payload, history });
  }

  async suggestions(code?: string): Promise<string[]> {
    const qs = code ? `?code=${encodeURIComponent(code)}` : "";
    const body = await this.http.get<{ items: string[] }>(`/chat/suggestions${qs}`);
    return body.items;
  }
}
