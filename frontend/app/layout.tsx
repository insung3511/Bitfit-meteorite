import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import SessionGate from "./SessionGate";
import LogoutButton from "./LogoutButton";

export const metadata: Metadata = {
  title: "Health Assistant",
  description: "Personal health assistant over your Fitbit/Google Health data.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className="h-full antialiased"
    >
      <body className="min-h-full flex flex-col">
        <header className="border-b border-black/10 dark:border-white/15">
          <nav className="mx-auto flex max-w-4xl items-center gap-6 px-6 py-4">
            <Link href="/" className="font-semibold">
              Health Assistant
            </Link>
            <div className="flex gap-4 text-sm">
              <Link href="/chat" className="hover:underline">
                Chat
              </Link>
              <Link href="/dashboard" className="hover:underline">
                Dashboard
              </Link>
            </div>
            <LogoutButton />
          </nav>
        </header>
        <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-8">
          <SessionGate>{children}</SessionGate>
        </main>
      </body>
    </html>
  );
}
