import "server-only";

export type ServiceName = "registry" | "weather" | "planner";

export class ApiError extends Error {
  readonly service: ServiceName;
  readonly status?: number;
  readonly code?: string;
  readonly detail: string;
  readonly kind: "http" | "network" | "timeout";

  constructor(init: {
    service: ServiceName;
    kind: "http" | "network" | "timeout";
    detail: string;
    status?: number;
    code?: string;
  }) {
    super(`${init.service}: ${init.detail}`);
    this.name = "ApiError";
    this.service = init.service;
    this.kind = init.kind;
    this.detail = init.detail;
    this.status = init.status;
    this.code = init.code;
  }
}
