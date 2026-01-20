"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import Image from "next/image";
import { MessageSquare, FileText, Network, Brain, Database, Cpu } from "lucide-react";
import { ShaderBackground } from "@/components/shader-background";

export default function Home() {
  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-black">
      {/* Animated gradient background */}
      <ShaderBackground />

      {/* Content */}
      <div className="relative z-10 flex min-h-screen flex-col items-center justify-center px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
          className="max-w-4xl text-center"
        >
          {/* Logo/Brand */}
          <motion.div
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.5 }}
            className="mb-8 inline-flex h-24 w-24 items-center justify-center rounded-2xl bg-gradient-to-br from-purple-500 to-pink-500 shadow-2xl shadow-purple-500/50 overflow-hidden"
          >
            <Image src="/logo.png" alt="LiveOS" width={96} height={96} className="h-24 w-24 object-contain" />
          </motion.div>

          {/* Title */}
          <motion.h1
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.2 }}
            className="mb-6 bg-gradient-to-r from-purple-400 via-pink-400 to-purple-400 bg-clip-text text-6xl font-bold tracking-tight text-transparent md:text-8xl"
          >
            LiveOS Brain
          </motion.h1>

          {/* Subtitle */}
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.4 }}
            className="mb-12 text-xl text-white/70 md:text-2xl"
          >
            Your multimodal, graph-based personal memory system
          </motion.p>

          {/* Features Grid */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.6 }}
            className="mb-12 grid grid-cols-1 gap-4 md:grid-cols-3"
          >
            <Link
              href="/chat"
              className="group rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur-xl transition-all hover:border-purple-500/50 hover:bg-white/10"
            >
              <MessageSquare className="mb-4 h-8 w-8 text-purple-400 transition-transform group-hover:scale-110" />
              <h3 className="mb-2 text-lg font-semibold text-white">Chat</h3>
              <p className="text-sm text-white/60">Talk to your brain and get insights</p>
            </Link>

            <Link
              href="/notes"
              className="group rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur-xl transition-all hover:border-pink-500/50 hover:bg-white/10"
            >
              <FileText className="mb-4 h-8 w-8 text-pink-400 transition-transform group-hover:scale-110" />
              <h3 className="mb-2 text-lg font-semibold text-white">Notes</h3>
              <p className="text-sm text-white/60">Capture your thoughts and ideas</p>
            </Link>

            <Link
              href="/graph"
              className="group rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur-xl transition-all hover:border-purple-500/50 hover:bg-white/10"
            >
              <Network className="mb-4 h-8 w-8 text-purple-400 transition-transform group-hover:scale-110" />
              <h3 className="mb-2 text-lg font-semibold text-white">Graph</h3>
              <p className="text-sm text-white/60">Visualize your knowledge network</p>
            </Link>
          </motion.div>

          {/* System Info */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.8, delay: 0.8 }}
            className="space-y-4"
          >
            <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 backdrop-blur-xl">
              <Brain className="h-4 w-4 text-purple-400" />
              <span className="text-sm text-white/80">
                Models: Gemma3, Whisper V3, Florence 2, Qwen3, MxBai Reranker, DeepSeek OCR
              </span>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 backdrop-blur-xl">
                <Database className="h-3 w-3 text-green-400" />
                <span className="text-xs text-white/70">Postgres</span>
              </div>
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 backdrop-blur-xl">
                <Network className="h-3 w-3 text-blue-400" />
                <span className="text-xs text-white/70">Neo4j</span>
              </div>
              <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 backdrop-blur-xl">
                <Cpu className="h-3 w-3 text-orange-400" />
                <span className="text-xs text-white/70">MinIO</span>
              </div>
            </div>
          </motion.div>
        </motion.div>
      </div>
    </div>
  );
}
