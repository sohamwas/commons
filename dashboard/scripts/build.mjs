// Production build, guarded against the dev server.
//
// `next build` and `next dev` fight over the build directory. A build launched while dev
// is live leaves the running server serving chunks that no longer exist, and the browser
// reports "Cannot find module './833.js'" — which reads like a code bug, sends you
// hunting through components, and is neither. It cost two debugging rounds here.
//
// The check is an actual HTTP request rather than a port bind: on Windows a bind to
// 127.0.0.1 can succeed even while another process holds 0.0.0.0 on the same port, so
// the bind test silently passed and the guard never fired.
import { spawn } from "node:child_process";

const DEV_PORT = 3300;

async function devServerRunning(port) {
  try {
    await fetch(`http://127.0.0.1:${port}/`, {
      signal: AbortSignal.timeout(2500),
    });
    return true;
  } catch {
    return false;
  }
}

if (await devServerRunning(DEV_PORT)) {
  console.error(
    `\n  The dev server is answering on :${DEV_PORT}.\n` +
      `  Building now would corrupt the chunks it is serving, and the browser would\n` +
      `  start reporting "Cannot find module './xxx.js'".\n\n` +
      `  Stop the dev server first, then run this again.\n`
  );
  process.exit(1);
}

const child = spawn("npx next build", {
  stdio: "inherit",
  shell: true,
  env: { ...process.env, NEXT_DIST_DIR: process.env.NEXT_DIST_DIR ?? ".next-build" },
});
child.on("exit", (code) => process.exit(code ?? 1));
