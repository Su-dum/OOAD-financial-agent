/**
 * HTTP 客户端（基础设施适配器）。
 *
 * 所有 Service 依赖这个类而不是直接 fetch，好处：
 *   - 换请求库（fetch -> axios）只改这里
 *   - 统一错误处理与超时
 *   - 测试时可注入 mock
 */
export class HttpError extends Error {
  constructor(readonly status: number, readonly detail: string) {
    super(`HTTP ${status}: ${detail}`);
    this.name = "HttpError";
  }
}

export class HttpClient {
  constructor(
    private readonly baseUrl: string = "/api",
    private readonly timeoutMs: number = 60_000,
  ) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.timeoutMs);
    try {
      const res = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        signal: ctrl.signal,
        headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      });
      if (!res.ok) {
        let detail = res.statusText;
        try {
          const body = await res.json();
          detail = body.detail ?? detail;
        } catch {
          /* 响应不是 JSON，忽略 */
        }
        throw new HttpError(res.status, String(detail));
      }
      return (await res.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  }

  get<T>(path: string): Promise<T> {
    return this.request<T>(path);
  }

  post<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>(path, { method: "POST", body: JSON.stringify(body) });
  }
}
