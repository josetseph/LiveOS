"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { Home, MessageSquare, FileText, Network, Box } from "lucide-react";
import { cn } from "@/lib/utils";

const navigation = [
  { name: "Home", href: "/", icon: Home },
  { name: "Chat", href: "/chat", icon: MessageSquare },
  { name: "Notes", href: "/notes", icon: FileText },
  { name: "Graph 2D", href: "/graph", icon: Network },
  { name: "Graph 3D", href: "/graph-3d", icon: Box },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-0 z-40 h-screen w-20 border-r border-white/10 bg-black/50 backdrop-blur-xl">
      <div className="flex h-full flex-col items-center py-8">
        {/* Logo */}
        <div className="mb-8 flex h-12 w-12 items-center justify-center rounded-xl overflow-hidden">
          <Image src="/logo-black-background.png" alt="LiveOS" width={48} height={48} className="h-full w-full object-cover" />
        </div>

        {/* Navigation */}
        <nav className="flex flex-1 flex-col gap-4">
          {navigation.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href;

            return (
              <Link
                key={item.name}
                href={item.href}
                className={cn(
                  "group relative flex h-12 w-12 items-center justify-center rounded-xl transition-all duration-200",
                  isActive
                    ? "bg-white/10 text-white shadow-lg shadow-purple-500/20"
                    : "text-white/50 hover:bg-white/5 hover:text-white"
                )}
                title={item.name}
              >
                <Icon className="h-5 w-5" />
                {isActive && (
                  <div className="absolute -left-1 top-1/2 h-8 w-1 -translate-y-1/2 rounded-r-full bg-gradient-to-b from-purple-500 to-pink-500" />
                )}
              </Link>
            );
          })}
        </nav>

        {/* System Info Badge */}
        <div className="mt-auto">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-green-500/10 text-green-500">
            <div className="h-2 w-2 animate-pulse rounded-full bg-green-500" />
          </div>
        </div>
      </div>
    </aside>
  );
}
