import Link from "next/link";

export default function PlotNotFound() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-4 py-10 sm:py-14">
      <h1 className="font-heading text-4xl font-bold text-primary sm:text-5xl">
        Plot not found
      </h1>
      <p className="max-w-prose text-lg text-muted-foreground">
        There is no plot at this address. It may have been removed, or the link
        may be wrong.
      </p>
      <Link
        href="/"
        className="inline-flex min-h-11 w-fit items-center rounded-lg bg-primary px-4 font-medium text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        Back to all farms
      </Link>
    </main>
  );
}
