const status = document.querySelector('#download-status');
document.querySelectorAll('[data-download]').forEach(button => button.addEventListener('click', async () => {
  const buttons = [...document.querySelectorAll('[data-download]')];
  buttons.forEach(b => b.disabled = true);
  try {
    if (!crypto.subtle) throw new Error('Use an HTTPS connection for verified downloads.');
    const response = await fetch('downloads/manifest.json');
    if (!response.ok) throw new Error('The review downloads are still being prepared.');
    const manifest = await response.json();
    const item = manifest[button.dataset.download];
    if (!item) throw new Error('This download is not available yet.');
    const parts = [];
    for (let i = 0; i < item.parts.length; i++) {
      status.textContent = `Downloading ${item.label}: part ${i + 1} of ${item.parts.length}…`;
      const chunk = await fetch(item.parts[i]);
      if (!chunk.ok) throw new Error(`Download part ${i + 1} failed. Please retry.`);
      parts.push(await chunk.arrayBuffer());
    }
    status.textContent = 'Verifying SHA-256…';
    const blob = new Blob(parts, {type: 'application/zip'});
    const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
    const actual = [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, '0')).join('');
    if (actual !== item.sha256) throw new Error('Checksum mismatch. No file was saved; please retry.');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob); link.download = item.filename;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    status.textContent = `${item.label} verified. Your browser should now save ${item.filename}.`;
  } catch (error) { status.textContent = error.message; }
  finally { buttons.forEach(b => b.disabled = false); }
}));
