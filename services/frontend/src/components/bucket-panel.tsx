"use client";

import { useId, useState, useTransition, type FormEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { suggestBucketAction } from "@/app/actions";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  bucketUrl,
  formatBucketPercent,
  parsePercentInput,
  suggestionText,
  validateLastIrrigation,
  type SuggestionView,
} from "@/lib/bucket";

type Problem = { message: string; plotGone?: boolean };

// The answer belongs to the date it was asked for. If the date changes, it is dropped.
type Answer = { date: string; view: SuggestionView };

const linkButton =
  "inline-flex min-h-11 items-center rounded-md px-1 font-medium text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

// Controlled inputs and useTransition with a manual onSubmit, not <form action>:
// React 19 resets a form after an action.
export function BucketPanel({
  plotId,
  bucketStart,
  irrigated,
  today,
  plantingDate,
  minDate,
  maxDate,
}: {
  plotId: string;
  bucketStart: number;
  irrigated: string | null;
  today: string;
  plantingDate: string;
  minDate: string;
  maxDate: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const panelId = useId();
  const dateId = useId();
  const percentId = useId();

  const [open, setOpen] = useState(false);
  const [date, setDate] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [percent, setPercent] = useState("");
  const [problem, setProblem] = useState<Problem | null>(null);
  const [suggesting, startSuggest] = useTransition();
  const [applying, startApply] = useTransition();

  const full = bucketStart === 1;
  const view = answer && answer.date === date ? answer.view : null;

  function reset() {
    setAnswer(null);
    setProblem(null);
    setPercent("");
  }

  function onDateChange(value: string) {
    setDate(value);
    reset();
  }

  function onSuggest(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (suggesting || applying) return;
    reset();
    const invalid = validateLastIrrigation(date, { today, plantingDate });
    if (invalid) {
      setProblem({ message: invalid });
      return;
    }
    const asked = date;
    startSuggest(async () => {
      const result = await suggestBucketAction(plotId, asked, plantingDate);
      if (result.ok) {
        setAnswer({ date: asked, view: result.data });
      } else {
        setProblem({ message: result.message, plotGone: result.plotGone });
      }
    });
  }

  function apply(fraction: number, since?: string) {
    setOpen(false);
    reset();
    startApply(() => {
      router.replace(bucketUrl(pathname, { bucketStart: fraction, irrigated: since }), {
        scroll: false,
      });
    });
  }

  function onApplyManual(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (applying) return;
    const fraction = parsePercentInput(percent);
    if (fraction === null) {
      setProblem({ message: "Enter a number from 0 to 100." });
      return;
    }
    apply(fraction);
  }

  return (
    <section aria-label="Assumed bucket level" className="flex flex-col gap-2">
      <p className="flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
        <span>
          {full
            ? "Assumed bucket: 100% (full)"
            : `Assumed bucket: ${formatBucketPercent(bucketStart)}`}
          {!full && irrigated !== null && (
            <>
              {"\u00a0· from irrigation on "}
              <span className="whitespace-nowrap">{irrigated}</span>
            </>
          )}
          <span aria-hidden>{"\u00a0·"}</span>
        </span>
        <span className="whitespace-nowrap">
          <button
            type="button"
            className={linkButton}
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? "Close" : "Change"}
          </button>
          {!full && <span aria-hidden>{"\u00a0·"}</span>}
        </span>
        {!full && (
          <Link href={pathname} replace scroll={false} className={linkButton}>
            Reset
          </Link>
        )}
      </p>

      {open && (
        <div
          id={panelId}
          className="flex flex-col gap-3 rounded-2xl bg-card p-4 ring-1 ring-foreground/15"
        >
          <form onSubmit={onSuggest} className="flex flex-col gap-2" noValidate>
            <Label htmlFor={dateId}>When did you last irrigate?</Label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                id={dateId}
                type="date"
                value={date}
                min={minDate}
                max={maxDate}
                onChange={(e) => onDateChange(e.target.value)}
                className="h-11 sm:max-w-56"
              />
              <Button
                type="submit"
                disabled={suggesting || applying}
                className="h-11 sm:h-11"
              >
                {suggesting ? "Checking…" : "Suggest"}
              </Button>
            </div>
          </form>

          {problem && (
            <Alert variant="destructive" role="alert">
              <AlertDescription>
                {problem.message}
                {problem.plotGone && (
                  <>
                    {" "}
                    <Link href="/" className="font-medium underline underline-offset-4">
                      All plots
                    </Link>
                  </>
                )}
              </AlertDescription>
            </Alert>
          )}

          {view?.kind === "value" && (
            <div className="flex flex-col gap-3" aria-live="polite">
              <p>{suggestionText(view)}</p>
              {view.stale && (
                <p className="text-sm text-muted-foreground">
                  Based on old weather data.
                </p>
              )}
              <div className="flex flex-col gap-2 sm:flex-row">
                <Button
                  type="button"
                  className="h-11"
                  disabled={applying}
                  onClick={() => apply(view.apply, view.since)}
                >
                  {`Apply ${view.percent}%`}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-11"
                  disabled={applying}
                  onClick={reset}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {view?.kind === "season_ended" && (
            <p aria-live="polite">The season has ended. There is nothing to water.</p>
          )}

          {view?.kind === "manual" && (
            <form onSubmit={onApplyManual} className="flex flex-col gap-2" noValidate>
              <p aria-live="polite">
                We don&apos;t have enough past weather to estimate this. Enter the
                bucket level yourself.
              </p>
              {view.stale && (
                <p className="text-sm text-muted-foreground">
                  Based on old weather data.
                </p>
              )}
              <Label htmlFor={percentId}>Bucket level (%)</Label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  id={percentId}
                  type="text"
                  inputMode="decimal"
                  autoComplete="off"
                  value={percent}
                  onChange={(e) => {
                    setPercent(e.target.value);
                    setProblem(null);
                  }}
                  className="h-11 sm:max-w-32"
                />
                <Button type="submit" className="h-11" disabled={applying}>
                  Apply
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-11"
                  disabled={applying}
                  onClick={reset}
                >
                  Cancel
                </Button>
              </div>
            </form>
          )}
        </div>
      )}
    </section>
  );
}
