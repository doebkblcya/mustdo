import {createHash} from 'node:crypto';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

// Mixkit permits these files in the rendered video, but the raw audio is not
// committed alongside source code. Download exact copies for local renders.
const assets = [
  {
    file: 'sfx/soft-switch-tap.wav',
    url: 'https://assets.mixkit.co/active_storage/sfx/2585/2585.wav',
    sha256: 'f8bcc70fca395b92ab2ef111ef874bf38c8659bc574452341f4e30bef4ec2397',
  },
  {
    file: 'sfx/air-sweep.wav',
    url: 'https://assets.mixkit.co/active_storage/sfx/166/166.wav',
    sha256: 'ca5a0206a7e6b12893a5727cb98a9d43ab02893153465eb21d43fb7b9e6616c3',
  },
  {
    file: 'sfx/gentle-bell.wav',
    url: 'https://assets.mixkit.co/active_storage/sfx/3109/3109.wav',
    sha256: '73ae1f6f85bd82729132429799df781d738a95d69165ab89d567cd70569d418d',
  },
  {
    file: 'music/digital-clouds.mp3',
    url: 'https://assets.mixkit.co/music/175/175.mp3',
    sha256: '71cd4ea39edcc7532672bd97311abadfd318d00e7a828310a88b4f57fad9cd48',
  },
];

const hash = (buffer) => createHash('sha256').update(buffer).digest('hex');

for (const asset of assets) {
  const destination = fileURLToPath(new URL(`../public/audio/${asset.file}`, import.meta.url));
  let existing;
  try {
    existing = await readFile(destination);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }

  if (existing) {
    if (hash(existing) !== asset.sha256) {
      throw new Error(`${asset.file} differs from the licensed source; move it aside before fetching again.`);
    }
    process.stdout.write(`Ready: ${asset.file}\n`);
    continue;
  }

  const response = await fetch(asset.url);
  if (!response.ok) throw new Error(`Could not download ${asset.file}: HTTP ${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  if (hash(bytes) !== asset.sha256) {
    throw new Error(`Source changed for ${asset.file}; verify the license and update the asset manifest.`);
  }

  await mkdir(dirname(destination), {recursive: true});
  await writeFile(destination, bytes, {flag: 'wx'});
  process.stdout.write(`Downloaded: ${asset.file}\n`);
}
