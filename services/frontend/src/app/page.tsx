import { StatusLine } from "@/components/status-line";

export const dynamic = "force-dynamic";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-6 px-4 py-16">
      <h1 className="text-6xl font-extrabold tracking-tight sm:text-7xl">
        AgroPilot
      </h1>
      <p className="max-w-prose text-lg text-muted-foreground">
        When to water each plot, and for how long.
      </p>
      <StatusLine />
    </main>
  );
}
