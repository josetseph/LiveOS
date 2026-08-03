import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { AiLimitedBanner } from "@/components/ai-limited-banner";
import { KBProvider } from "@/lib/kb-context";
import { ChatProvider } from "@/lib/chat-context";
import { SuppressThreeWarnings } from "@/components/suppress-three-warnings";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "Orb",
  description: "Your multimodal, graph-based personal memory system",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/logo-icon.png", type: "image/png", sizes: "128x128" },
    ],
    apple: "/logo-icon.png",
    shortcut: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} font-sans antialiased`}>
        <KBProvider>
          <ChatProvider>
            <SuppressThreeWarnings />
            <Sidebar />
            <main className="ml-20 min-h-screen">{children}</main>
            <AiLimitedBanner />
          </ChatProvider>
        </KBProvider>
      </body>
    </html>
  );
}
