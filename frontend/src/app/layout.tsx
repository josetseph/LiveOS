import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { CustomCursor } from "@/components/custom-cursor";
import { GrainOverlay } from "@/components/grain-overlay";
import { KBProvider } from "@/lib/kb-context";
import { ChatProvider } from "@/lib/chat-context";
import { SuppressThreeWarnings } from "@/components/suppress-three-warnings";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "LiveOS",
  description: "Your multimodal, graph-based personal memory system",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      {
        url: "/logo-black-background.png",
        sizes: "192x192",
        type: "image/png",
      },
      {
        url: "/logo-black-background.png",
        sizes: "512x512",
        type: "image/png",
      },
    ],
    apple: "/logo-black-background.png",
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
      <head>
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="icon" href="/logo-black-background.png" type="image/png" />
        <link rel="apple-touch-icon" href="/logo-black-background.png" />
      </head>
      <body className={`${inter.variable} font-sans antialiased`}>
        <KBProvider>
          <ChatProvider>
            <SuppressThreeWarnings />
            <CustomCursor />
            <GrainOverlay />
            <Sidebar />
            <main className="ml-20 min-h-screen">{children}</main>
          </ChatProvider>
        </KBProvider>
      </body>
    </html>
  );
}
