import type { Metadata } from "next";
import { Suspense } from "react";
import { Fraunces, Inter } from "next/font/google";
import { Toaster } from "sonner";
import { ServiceBar, ServiceBarFallback } from "@/components/service-bar";
import "./globals.css";

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  weight: ["600", "700"],
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "AgroPilot",
  description: "When to water each plot, and for how long.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${fraunces.variable} ${inter.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Suspense fallback={<ServiceBarFallback />}>
          <ServiceBar />
        </Suspense>
        {children}
        <Toaster position="top-center" richColors closeButton duration={6000} />
      </body>
    </html>
  );
}
