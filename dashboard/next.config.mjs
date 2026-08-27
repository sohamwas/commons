/** @type {import('next').NextConfig} */
// Static export: the recorded-run demo on the marketing site is the SAME components the
// local dashboard uses, with no backend at all.
//
// distDir is overridable because `next build` and `next dev` both write to `.next` by
// default. Running a production build while the dev server is live overwrites the chunks
// it is serving, and the browser then dies with "Cannot find module './833.js'" — which
// looks like a code bug and is not one. Builds go somewhere else instead.
const nextConfig = {
  output: "export",
  distDir: process.env.NEXT_DIST_DIR || ".next",
  images: { unoptimized: true },
};
export default nextConfig;
