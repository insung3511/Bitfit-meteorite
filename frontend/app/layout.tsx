import type { Metadata } from "next";
import "./globals.css";
import SessionGate from "./SessionGate";
import ToastContainer from "./components/Toast";
import GridBackground from "./components/GridBackground";
import Sidebar from "./components/Sidebar";

export const metadata: Metadata = {
  title: "BitFit Meteorite",
  description: "Personal health signals, visualized.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full" style={{ background: "var(--bg-primary)" }}>
        <GridBackground />
        <Sidebar />
        <main className="relative z-10 min-h-screen w-full" style={{ marginLeft: "56px" }}>
          <SessionGate>{children}</SessionGate>
        </main>
        <ToastContainer />
      </body>
    </html>
  );
}
