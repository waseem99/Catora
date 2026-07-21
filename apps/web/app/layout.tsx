import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Catora — AI Commerce Intelligence",
  description: "Enterprise catalog intelligence and buyer-intent coverage.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
