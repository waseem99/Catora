import { z } from "zod";

export const HealthResponseSchema = z.object({
  status: z.literal("ok"),
  service: z.string().min(1),
  version: z.string().min(1),
});

export type HealthResponse = z.infer<typeof HealthResponseSchema>;

export const ReadinessDependencySchema = z.object({
  name: z.string(),
  status: z.enum(["ok", "error"]),
  detail: z.string().optional(),
});

export const ReadinessResponseSchema = z.object({
  status: z.enum(["ready", "not_ready"]),
  dependencies: z.array(ReadinessDependencySchema),
});

export type ReadinessResponse = z.infer<typeof ReadinessResponseSchema>;
