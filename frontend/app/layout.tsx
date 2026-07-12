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
        <header className="border-b border-[#2f3434] bg-[#141617] text-[#f7f7f2]">
          <nav className="mx-auto flex w-full max-w-[1440px] items-center gap-6 px-5 py-3 lg:px-8">
            <Link href="/" className="flex items-center gap-3 font-semibold tracking-tight">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#f3c400] text-sm font-black text-[#141617]">+</span>
              <span>BITFIT<span className="text-white/45"> / </span>HEALTH OS</span>
            </Link>
            <div className="ml-auto flex items-center gap-1 text-xs font-bold uppercase tracking-[0.12em] text-white/55">
              <Link href="/dashboard" className="rounded px-3 py-2 hover:bg-white/10 hover:text-white">Board</Link>
              <Link href="/chat" className="rounded px-3 py-2 hover:bg-white/10 hover:text-white">Assistant</Link>
            </div>
            <div className="hidden h-5 w-px bg-white/15 sm:block" />
            <div className="hidden items-center gap-2 text-[10px] font-bold uppercase tracking-[0.12em] text-white/45 sm:flex">
              <span className="h-2 w-2 rounded-full bg-[#17a66b]" />
              Private workspace
            </div>
            <LogoutButton />
          </nav>
        </header>
        <main className="mx-auto w-full max-w-[1440px] flex-1 px-5 py-6 lg:px-8 lg:py-8">
          <SessionGate>{children}</SessionGate>
        </main>
      </body>
    </html>
  );
}
