/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Tauri loads the static export; there is no Node server in the desktop app.
  output: "export",
  images: { unoptimized: true },
};

export default nextConfig;
