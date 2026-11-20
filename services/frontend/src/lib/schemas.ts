import { z } from "zod";

export const farmSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Enter a farm name")
    .refine((v) => !v.includes("\0"), "The name contains an invalid character"),
});

export type FarmInput = z.infer<typeof farmSchema>;
