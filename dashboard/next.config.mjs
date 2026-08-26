/** @type {import('next').NextConfig} */
// Static export: the hosted demo is a recorded run replayed by the SAME components the
// local app uses, with no backend at all (handoff §15.3).
const nextConfig = { output: "export", images: { unoptimized: true } };
export default nextConfig;
