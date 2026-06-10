import type { NextConfig } from "next";

const apiProxyTarget =
  process.env.API_PROXY_TARGET ??
  (process.env.NODE_ENV === "development"
    ? "http://localhost:8700"
    : "http://backend:8000");

const filesProxyTarget =
  process.env.FILES_PROXY_TARGET ??
  (process.env.NODE_ENV === "development"
    ? "http://localhost:9000"
    : "http://rustfs:9000");

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiProxyTarget}/api/v1/:path*`,
      },
      {
        source: "/health",
        destination: `${apiProxyTarget}/health`,
      },
      {
        source: "/files/:path*",
        destination: `${filesProxyTarget}/:path*`,
      },
    ];
  },
};

export default nextConfig;
