import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';

// Version and build stamp: "v0.12.0 · Build 9BA1C88E.014". The build ID is the build time
// as YYMMDDHHMM written in hex, then a counter kept in .build-seq at the project root
// (gitignored). Only real builds take a build ID, so test runs never bump the counter.
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string };
const ROOT = fileURLToPath(new URL('..', import.meta.url));
function git(args: string): string {
  try {
    return execFileSync('git', args.split(' '), { cwd: ROOT, stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim();
  } catch {
    return '';
  }
}
/** Short commit hash, with "-dirty" when built from uncommitted changes. */
function commit(): string {
  const hash = git('rev-parse --short HEAD') || 'dev';
  return git('status --porcelain') ? `${hash}-dirty` : hash;
}
function buildId(): string {
  const seqFile = join(ROOT, '.build-seq');
  try {
    const seq = (Number.parseInt(existsSync(seqFile) ? readFileSync(seqFile, 'utf8').trim() : '0', 10) || 0) + 1;
    writeFileSync(seqFile, String(seq));
    const d = new Date();
    const two = (n: number) => String(n).padStart(2, '0');
    const stamp = `${two(d.getFullYear() % 100)}${two(d.getMonth() + 1)}${two(d.getDate())}${two(d.getHours())}${two(d.getMinutes())}`;
    return `${Number(stamp).toString(16).toUpperCase()}.${String(seq % 1000).padStart(3, '0')}`;
  } catch {
    return 'dev';
  }
}

const backend = 'http://127.0.0.1:8791';

export default defineConfig(({ command, mode }) => {
  const building = command === 'build' && mode !== 'test';
  const stamp = {
    version: pkg.version,
    build: building ? buildId() : 'dev',
    commit: commit(),
    built: new Date().toISOString(),
  };
  // build.json next to index.html, so `vm --version` reports the build the phone gets.
  const buildJson: Plugin = {
    name: 'vm-build-json',
    apply: 'build',
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'build.json', source: JSON.stringify(stamp, null, 2) + '\n' });
    },
  };
  return {
  base: '/',
  plugins: [react(), buildJson],
  define: {
    __APP_VERSION__: JSON.stringify(stamp.version),
    __APP_BUILD_ID__: JSON.stringify(stamp.build),
    __APP_COMMIT__: JSON.stringify(stamp.commit),
    __APP_BUILT__: JSON.stringify(stamp.built),
  },
  server: {
    proxy: {
      '/api': { target: backend },
      '/pair': { target: backend },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
};
});
