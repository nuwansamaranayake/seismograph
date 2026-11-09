/** Static export: the FastAPI container serves the built pages from the same hostname.
 * No node runtime in production. One less process on a shared host. */
const nextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};
export default nextConfig;
