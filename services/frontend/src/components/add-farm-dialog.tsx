"use client";

import { useActionState, useState } from "react";
import { toast } from "sonner";
import { createFarmAction } from "@/app/actions";
import type { ActionResult } from "@/lib/action-result";
import { farmSchema } from "@/lib/schemas";
import type { Farm } from "@/lib/types";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function FarmForm({ onDone }: { onDone: () => void }) {
  // Controlled, because React resets uncontrolled fields after an action runs.
  const [name, setName] = useState("");

  const [state, formAction, pending] = useActionState(
    async (
      prev: ActionResult<Farm> | null,
      formData: FormData,
    ): Promise<ActionResult<Farm>> => {
      const parsed = farmSchema.safeParse({ name: formData.get("name") });
      if (!parsed.success) {
        return {
          ok: false,
          kind: "validation",
          message: "Please fix the highlighted fields.",
          fieldErrors: { name: parsed.error.issues[0].message },
        };
      }
      const result = await createFarmAction(prev, formData);
      if (result.ok) {
        toast.success("Farm created");
        onDone();
      }
      return result;
    },
    null,
  );

  const failed = state && !state.ok ? state : null;
  const nameError = failed?.fieldErrors?.name;
  const formError = failed && !nameError ? failed.message : null;

  return (
    <form action={formAction} noValidate className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor="farm-name">Name</Label>
        <Input
          id="farm-name"
          name="name"
          maxLength={100}
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoComplete="off"
          autoFocus
          aria-invalid={nameError ? true : undefined}
          aria-describedby={nameError ? "farm-name-error" : undefined}
          className="h-11"
        />
        {nameError && (
          <p id="farm-name-error" className="text-sm text-destructive">
            {nameError}
          </p>
        )}
      </div>
      {formError && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{formError}</AlertDescription>
        </Alert>
      )}
      <Button type="submit" disabled={pending} className="h-11 w-full sm:w-auto sm:self-end">
        {pending ? "Creating…" : "Create farm"}
      </Button>
    </form>
  );
}

export function AddFarmDialog() {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={<Button variant="outline" className="h-11 min-h-11 px-4" />}
      >
        + Farm
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New farm</DialogTitle>
          <DialogDescription>Give the farm a name.</DialogDescription>
        </DialogHeader>
        <FarmForm onDone={() => setOpen(false)} />
      </DialogContent>
    </Dialog>
  );
}
