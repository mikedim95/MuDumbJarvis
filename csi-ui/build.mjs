import {build} from 'esbuild';
import {mkdir,copyFile,writeFile,readFile,readdir} from 'node:fs/promises';
const out=new URL('../server/hud/csi/',import.meta.url);
await mkdir(out,{recursive:true});
await build({entryPoints:[new URL('src/index.jsx',import.meta.url).pathname],
  outfile:new URL('csi-workspace.js',out).pathname,bundle:true,minify:true,
  format:'iife',target:['es2022'],jsx:'automatic',legalComments:'linked',
  define:{'process.env.NODE_ENV':'"production"'},loader:{'.woff': 'dataurl','.woff2':'dataurl','.ttf':'dataurl'}});
await copyFile(new URL('vendor/cyberdeck-ui/LICENSE',import.meta.url),new URL('CYBERDECK-LICENSE.txt',out));
const lock=JSON.parse(await readFile(new URL('package-lock.json',import.meta.url),'utf8'));
const licenses=[];
for(const name of Object.keys(lock.packages).filter(name=>name.startsWith('node_modules/'))){
 const dir=new URL(name+'/',import.meta.url);
 try{
  const pkg=JSON.parse(await readFile(new URL('package.json',dir),'utf8'));
  for(const file of (await readdir(dir)).filter(file=>/^(licen[sc]e|copying|notice)(\.|$)/i.test(file))){
   try{licenses.push(pkg.name+'@'+pkg.version+' — '+file+'\n'+await readFile(new URL(file,dir),'utf8'));}catch{}
  }
 }catch{}
}
await writeFile(new URL('THIRD_PARTY_LICENSES.txt',out),licenses.join('\n\n'+'='.repeat(72)+'\n\n'));
await writeFile(new URL('.gitattributes',out),'csi-workspace.js -whitespace\ncsi-workspace.css -whitespace\n*.LEGAL.txt -whitespace\nTHIRD_PARTY_LICENSES.txt -whitespace\n');
