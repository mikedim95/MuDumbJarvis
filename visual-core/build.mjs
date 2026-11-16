import {build} from 'esbuild';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
const out = new URL('../server/hud/core/', import.meta.url);
await mkdir(out, {recursive: true});
await build({entryPoints: [new URL('src/index.js', import.meta.url).pathname],
  outfile: new URL('visual-core.js', out).pathname, bundle: true, minify: true,
  format: 'iife', target: ['es2020'], legalComments: 'none',
  banner: {js: '/*! JARVIS particle core. Adapted from zhisandesu/audio-reactive-particle-field (MIT). Three.js (MIT). See LICENSE.txt. */'}});
const upstream = await readFile(new URL('vendor/audio-reactive-particle-field/LICENSE', import.meta.url), 'utf8');
const three = await readFile(new URL('node_modules/three/LICENSE', import.meta.url), 'utf8');
await writeFile(new URL('LICENSE.txt', out),
  'audio-reactive-particle-field — https://github.com/zhisandesu/audio-reactive-particle-field\n' +
  'Pinned source: a1fba5dc0687ec8145acd83fe316103272863356\n\n' + upstream + '\n\nThree.js\n\n' + three);
