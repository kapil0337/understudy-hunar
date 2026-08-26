import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/shell/AppShell";
import { ThemeProvider } from "@/components/shell/ThemeProvider";

// Runs before hydration (strategy="beforeInteractive") so <html> already has the right class by
// first paint — no flash of the wrong theme. ThemeProvider re-derives the same value from
// localStorage after mount purely to drive the toggle's own UI state; it never needs to touch
// the class itself on first render because this already did.
const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem("understudy-theme");
    var dark = stored === "dark" || (stored !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
  } catch (e) {}
})();
`;

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Understudy",
  description:
    "Rehearse-then-dial voice recruiting on the Hunar Voice Agents API.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <Script id="theme-init" strategy="beforeInteractive">
          {THEME_INIT_SCRIPT}
        </Script>
        <ThemeProvider>
          <Providers>
            <AppShell>{children}</AppShell>
          </Providers>
        </ThemeProvider>
      </body>
    </html>
  );
}
