import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JARVIS_ | Autonomous Execution Workspace",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full flex flex-col font-mono text-xs overflow-hidden antialiased bg-fra-cream text-black">
        {children}
      </body>
    </html>
  );
}
