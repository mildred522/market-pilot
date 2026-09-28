import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NODE_ENV === "development" ? ".next-dev" : ".next",
  // The launcher deliberately opens 127.0.0.1 while Next commonly advertises
  // localhost. Declare both development origins so HMR does not repeatedly
  // reject the browser connection and trigger route re-renders.
  allowedDevOrigins: ["127.0.0.1", "localhost"]
};

export default nextConfig;
