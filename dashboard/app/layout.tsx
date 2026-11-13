import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DSP Campaign Analyst",
  description: "Campaign performance, pacing and auction insights on the iPinYou dataset",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}