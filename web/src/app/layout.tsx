import type { Metadata } from "next";

import "./globals.css";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "OpenFR Research Terminal",
  description: "Dark mode AI financial research dashboard for OpenFR"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="dark">
      <body className={cn("font-sans")}>{children}</body>
    </html>
  );
}
