import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Touchstone", template: "%s · Touchstone" },
  description:
    "The verification layer for AI. Register verifiers, score risk, audit every decision, and measure robustness against manipulation.",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
