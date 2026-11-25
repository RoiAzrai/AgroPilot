"use client";

import {
  startTransition,
  useActionState,
  useEffect,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { createPlotAction } from "@/app/actions";
import type { ActionResult } from "@/lib/action-result";
import {
  firstIssuePerField,
  latestDateOnEarth,
  plotInputFromFormData,
  plotSchema,
  type PlotField,
} from "@/lib/schemas";
import type { Catalogs, Farm } from "@/lib/types";
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
import { UseMyLocation } from "@/components/use-my-location";
import { cn } from "cn";

type Values = Record<Exclude<PlotField, "farm_id">, string>;

const EMPTY: Values = {
  name: "",
  crop_id: "",
  planting_date: "",
  soil_id: "",
  emitter_id: "",
  area_m2: "",
  row_spacing_m: "",
  emitter_spacing_m: "",
  lat: "",
  lon: "",
};

// Inputs stay at 16px on every screen: below that, iOS zooms in on focus.
const INPUT = "h-11 text-base md:text-base";
const SELECT = cn(
  "w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 outline-none transition-colors",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
  "aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20",
  "dark:bg-input/30",
  INPUT,
);

function Field({
  id,
  label,
  error,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error && (
        <p id={`${id}-error`} className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

function PlotForm({
  farm,
  catalogs,
  onDone,
}: {
  farm: Farm;
  catalogs: Catalogs;
  onDone: () => void;
}) {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  // Controlled, because React resets uncontrolled fields after an action runs.
  const [values, setValues] = useState<Values>(EMPTY);
  const set = (key: keyof Values) => (value: string) =>
    setValues((v) => ({ ...v, [key]: value }));

  const [state, formAction, pending] = useActionState(
    async (
      prev: ActionResult<{ id: string }> | null,
      formData: FormData,
    ): Promise<ActionResult<{ id: string }>> => {
      const parsed = plotSchema.safeParse(plotInputFromFormData(formData));
      if (!parsed.success) {
        return {
          ok: false,
          kind: "validation",
          message: "Please fix the highlighted fields.",
          fieldErrors: firstIssuePerField(parsed.error),
        };
      }
      const result = await createPlotAction(prev, formData);
      if (result.ok) {
        toast.success("Plot created");
        onDone();
        router.push(`/plots/${result.data.id}`);
      }
      return result;
    },
    null,
  );

  const failed = state && !state.ok ? state : null;
  const errors = failed?.fieldErrors ?? {};
  const formError =
    failed && !Object.keys(errors).some((k) => k in EMPTY) ? failed.message : null;

  // Move focus to the first invalid field (DOM order is visual order).
  useEffect(() => {
    if (failed) {
      formRef.current
        ?.querySelector<HTMLElement>('[aria-invalid="true"]')
        ?.focus();
    }
  }, [failed]);

  const props = (key: keyof Values) => ({
    id: `plot-${key}`,
    name: key,
    value: values[key],
    "aria-invalid": errors[key] ? (true as const) : undefined,
    "aria-describedby": errors[key] ? `plot-${key}-error` : undefined,
  });
  const text = (key: keyof Values, extra: object = {}) => ({
    ...props(key),
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => set(key)(e.target.value),
    className: INPUT,
    autoComplete: "off",
    ...extra,
  });
  const decimal = (key: keyof Values) => text(key, { type: "text", inputMode: "decimal" });
  const select = (key: keyof Values) => ({
    ...props(key),
    onChange: (e: React.ChangeEvent<HTMLSelectElement>) => set(key)(e.target.value),
    className: SELECT,
  });

  // React 19 resets <form action> after the action finishes, which clears native <select>
  // values even though state still holds them; so we submit manually.
  return (
    <form
      ref={formRef}
      noValidate
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        const data = new FormData(e.currentTarget);
        startTransition(() => formAction(data));
      }}
    >
      <input type="hidden" name="farm_id" value={farm.id} />

      <Field id="plot-name" label="Name" error={errors.name}>
        <Input {...text("name")} type="text" maxLength={100} autoFocus />
      </Field>

      <Field id="plot-crop_id" label="Crop" error={errors.crop_id}>
        <select {...select("crop_id")}>
          <option value="">Choose…</option>
          {catalogs.crops.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </Field>

      <Field id="plot-soil_id" label="Soil" error={errors.soil_id}>
        <select {...select("soil_id")}>
          <option value="">Choose…</option>
          {catalogs.soils.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.available_water_mm_per_m} mm/m)
            </option>
          ))}
        </select>
      </Field>

      <Field id="plot-emitter_id" label="Emitter" error={errors.emitter_id}>
        <select {...select("emitter_id")}>
          <option value="">Choose…</option>
          {catalogs.emitters.map((e) => (
            <option key={e.id} value={e.id}>
              {e.name} ({e.flow_lph} L/h)
            </option>
          ))}
        </select>
      </Field>

      <Field id="plot-planting_date" label="Planting date" error={errors.planting_date}>
        <Input
          {...text("planting_date")}
          type="date"
          max={latestDateOnEarth(new Date())}
        />
      </Field>

      <Field id="plot-area_m2" label="Area (m²)" error={errors.area_m2}>
        <Input {...decimal("area_m2")} />
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="plot-row_spacing_m" label="Row spacing (m)" error={errors.row_spacing_m}>
          <Input {...decimal("row_spacing_m")} />
        </Field>
        <Field
          id="plot-emitter_spacing_m"
          label="Emitter spacing (m)"
          error={errors.emitter_spacing_m}
        >
          <Input {...decimal("emitter_spacing_m")} />
        </Field>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field id="plot-lat" label="Latitude" error={errors.lat}>
          <Input {...decimal("lat")} />
        </Field>
        <Field id="plot-lon" label="Longitude" error={errors.lon}>
          <Input {...decimal("lon")} />
        </Field>
      </div>

      <UseMyLocation
        onLocate={(lat, lon) => setValues((v) => ({ ...v, lat, lon }))}
      />

      {formError && (
        <Alert variant="destructive" role="alert">
          <AlertDescription>{formError}</AlertDescription>
        </Alert>
      )}
      <Button type="submit" disabled={pending} className="h-11 w-full sm:w-auto sm:self-end">
        {pending ? "Creating…" : "Create plot"}
      </Button>
    </form>
  );
}

export function AddPlotDialog({
  farm,
  catalogs,
}: {
  farm: Farm;
  // null when any catalogue failed to load
  catalogs: Catalogs | null;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button
            variant="outline"
            className="h-auto min-h-11 gap-1.5 rounded-[10px] border-[1.5px] border-primary bg-transparent px-4 py-2.5 text-[14px] leading-[normal] font-semibold text-primary hover:bg-primary/5 hover:text-primary aria-expanded:bg-primary/5 aria-expanded:text-primary"
          />
        }
      >
        <svg aria-hidden width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="size-[14px]"><path d="M8 3v10M3 8h10" /></svg>
        Add plot
      </DialogTrigger>
      <DialogContent
        className={cn(
          "max-sm:top-0 max-sm:left-0 max-sm:h-dvh max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none max-sm:overflow-y-auto",
          "content-start sm:max-h-[90dvh] sm:max-w-lg sm:overflow-y-auto",
        )}
      >
        <DialogHeader>
          <DialogTitle>New plot in {farm.name}</DialogTitle>
          <DialogDescription>All fields are required.</DialogDescription>
        </DialogHeader>
        {catalogs ? (
          <PlotForm farm={farm} catalogs={catalogs} onDone={() => setOpen(false)} />
        ) : (
          <Alert variant="destructive" role="alert">
            <AlertDescription>
              Can&apos;t load crops, soils or emitters. Try again later.
            </AlertDescription>
          </Alert>
        )}
      </DialogContent>
    </Dialog>
  );
}
