/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8080";
    return {
      // The public landing page is a static file; the app starts at /overview
      beforeFiles: [{ source: "/", destination: "/landing/index.html" }],
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
