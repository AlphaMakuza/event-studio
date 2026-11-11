// Recover from Sites' per-push size limit. Credential input is hidden and never saved.
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '..');
if (process.stdin.isTTY) process.stdin.setRawMode(true);
process.stderr.write('Ready for Site credential JSON on stdin (input is hidden).\n');
let buffer = '';
const credential = await new Promise((resolve, reject) => {
  process.stdin.setEncoding('utf8');
  function onData(chunk) {
    if (chunk.includes('\u0003')) {process.exit(130);}
    buffer += chunk;
    if (buffer.includes('\n') || buffer.includes('\r')) {
      process.stdin.off('data', onData); process.stdin.pause();
      if (process.stdin.isTTY) process.stdin.setRawMode(false);
      try { resolve(JSON.parse(buffer.trim())); } catch { reject(new Error('Invalid credential input')); }
      buffer = '';
    }
  }
  process.stdin.on('data', onData);
});
async function git(args) {
  const env = {...process.env, GIT_TERMINAL_PROMPT: '0', SITES_GIT_AUTHORIZATION: `Authorization: Bearer ${credential.token}`};
  for (const key of Object.keys(env)) if (key.startsWith('GIT_TRACE') || key === 'GIT_CURL_VERBOSE') delete env[key];
  const auth = ['-c', 'credential.helper=', '-c', 'http.extraHeader=', '-c', 'http.followRedirects=false',
    `--config-env=http.${credential.remote_url}.extraHeader=SITES_GIT_AUTHORIZATION`];
  return await new Promise((resolve, reject) => {
    const child = spawn('git', [...auth, ...args], {cwd: path.join(root, 'website'), env, stdio: ['ignore','pipe','pipe']});
    let output = '', errors = '';
    child.stdout.on('data', x => output += x); child.stderr.on('data', x => errors += x);
    child.on('error', () => reject(new Error('Could not start Git')));
    child.on('close', code => code ? reject(new Error(errors.split(credential.token).join('[redacted]'))) : resolve(output.trim()));
  });
}
try {
  const plan = JSON.parse(readFileSync(path.join(root, 'artifacts/site-upload-plan.json'), 'utf8'));
  const advertised = await git(['ls-remote', '--heads', credential.remote_url, `refs/heads/${credential.branch}`]);
  const remoteHead = advertised.split(/\s+/)[0];
  const start = remoteHead ? plan.commits.indexOf(remoteHead) + 1 : 0;
  if (remoteHead && start === 0) throw new Error('Remote has unexpected history; preserve it and reconcile.');
  for (let i = start; i < plan.commits.length; i++) {
    await git(['push', credential.remote_url, `${plan.commits[i]}:refs/heads/${credential.branch}`]);
    process.stdout.write(`Uploaded batch ${i + 1}/${plan.commits.length}\n`);
  }
  const remote = await git(['ls-remote', '--heads', credential.remote_url, `refs/heads/${credential.branch}`]);
  if (!remote.startsWith(plan.commits.at(-1))) throw new Error('Final source verification failed');
  process.stdout.write(`Verified pushed Site commit ${plan.commits.at(-1)}\n`);
} catch (error) {process.stderr.write(error.message + '\n'); process.exitCode = 1;}
