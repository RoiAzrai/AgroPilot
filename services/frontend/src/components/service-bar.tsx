import { checkAll } from "@/lib/health";

const SERVICES = [
  { key: "registry", label: "Registry" },
  { key: "weather", label: "Weather" },
  { key: "planner", label: "Planner" },
] as const;

// Fixed height, so the fallback and the loaded bar never shift the page.
// One row on every width, no wrapping. Below sm: no "Services" label, no pills, and the
// status word only when a service is down. Every breakpoint keeps "up"/"down" for screen readers.
function Shell({ children }: { children: React.ReactNode }) {
  return (
    <header className="bg-primary text-background leading-[normal]">
      <div className="mx-auto flex h-11 max-w-[1120px] items-center gap-3 overflow-hidden whitespace-nowrap px-4 sm:h-16 sm:overflow-x-auto sm:gap-2.5 sm:px-6">
        <span className="hidden shrink-0 text-service-bar-foreground sm:mr-1 sm:inline sm:text-[13px]">
          Services
        </span>
        {children}
      </div>
    </header>
  );
}

export async function ServiceBar() {
  const health = await checkAll();
  return (
    <Shell>
      <ul aria-label="Service status" className="flex items-center gap-3.5 sm:gap-2.5">
        {SERVICES.map(({ key, label }) => {
          const up = health[key] === "up";
          return (
            <li
              key={key}
              className="inline-flex shrink-0 items-center gap-1.5 text-[13px] font-medium sm:gap-2 sm:rounded-full sm:bg-service-bar sm:px-3.5 sm:py-2 sm:text-[14px]"
            >
              <span
                aria-hidden
                className={
                  up
                    ? "size-[9px] rounded-full bg-dot-up shadow-[0_0_0_3px_rgba(111,207,127,0.25)] sm:size-2.5"
                    : "size-[9px] rounded-full bg-dot-down shadow-[0_0_0_3px_rgba(229,72,77,0.3)] sm:size-2.5"
                }
              />
              {label}
              <span
                className={`text-[11px] text-service-bar-foreground sm:text-[12px] ${
                  up ? "sr-only sm:not-sr-only" : ""
                }`}
              >
                {up ? "up" : "down"}
              </span>
            </li>
          );
        })}
      </ul>
    </Shell>
  );
}

export function ServiceBarFallback() {
  return (
    <Shell>
      <span className="text-[13px] text-service-bar-foreground sm:text-[14px]">
        Checking…
      </span>
    </Shell>
  );
}
