/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  distDir: process.env.NEXT_DIST_DIR || ".next",
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8080";
    return {
      // The public landing page is static; operations start at /mission-control.
      beforeFiles: [
        { source: "/", destination: "/home/index.html" },
        { source: "/how-it-works", destination: "/how-it-works/index.html" },
      ],
      afterFiles: [
        {
          source: "/api/:path*",
          destination: `${backendUrl}/:path*`,
        },
      ],
    };
  },
};
module.exports = nextConfig;
