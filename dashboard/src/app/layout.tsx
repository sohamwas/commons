import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Commons",
  description:
    "An MCP-layer arbitration gateway that enforces policy on the entity being acted upon rather than the agent doing the acting.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
