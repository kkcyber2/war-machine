import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "War Machine — Shadow Agency",
  description: "Autonomous AI Lead Hunting & Outreach Intelligence",
  icons: { icon: "/favicon.ico" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-obsidian min-h-screen bg-grid antialiased">
        {children}
      </body>
    </html>
  );
}
