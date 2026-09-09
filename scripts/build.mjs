import { readFile, mkdir, cp, rm } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
for (const file of ['src/calculator.mjs', 'src/app.mjs']) {
  const result = spawnSync(process.execPath, ['--check', file], { stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`Syntax check failed: ${file}`);
}
const html = await readFile('index.html', 'utf8');
for (const asset of ['./src/styles.css', './src/app.mjs']) {
  if (!html.includes(asset)) throw new Error(`Missing reference: ${asset}`);
  await readFile(asset);
}
await rm('dist', { recursive: true, force: true });
await mkdir('dist');
await cp('index.html', 'dist/index.html');
await cp('src', 'dist/src', { recursive: true });
console.log('Built static calculator into dist/');
