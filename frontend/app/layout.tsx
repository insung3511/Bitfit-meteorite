import type { Metadata } from "next";
import "./globals.css";
import SessionGate from "./SessionGate";
import FloatingUtilityDock from "./FloatingUtilityDock";
import ToastContainer from "./components/Toast";
import AmbientBackground from "./components/AmbientBackground";

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
      <body className="min-h-full">
        <AmbientBackground />
        <main className="relative z-10 min-h-screen w-full">
          <SessionGate>{children}</SessionGate>
        </main>
        <FloatingUtilityDock />
        <ToastContainer />
      </body>
    </html>
  );
}
