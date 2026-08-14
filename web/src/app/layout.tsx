import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Nightmare Studio — Production Desk", description: "Human-gated horror video production operations" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
