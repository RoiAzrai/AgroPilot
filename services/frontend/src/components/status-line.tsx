import { CircleAlert, CircleCheck } from "lucide-react";
import { checkAll } from "@/lib/health";

const LABELS = ["registry", "weather", "planner"] as const;

export async function StatusLine() {
  const health = await checkAll();

  return (
    <ul
      aria-label="Service status"
      className="flex flex-wrap gap-x-6 gap-y-2 text-sm"
    >
      {LABELS.map((name) => {
        const up = health[name] === "up";
        const Icon = up ? CircleCheck : CircleAlert;
        return (
          <li
            key={name}
            className={`flex items-center gap-2 font-medium ${
              up ? "text-status-up" : "text-status-down"
            }`}
          >
            <Icon aria-hidden className="size-4" />
            <span className="text-foreground">{name}</span>
            <span>{up ? "up" : "down"}</span>
          </li>
        );
      })}
    </ul>
  );
}
