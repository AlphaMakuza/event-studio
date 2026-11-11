"""Verify workspace code/assets against the executable and website upload ZIP."""
import hashlib
import json
from pathlib import Path
import zipfile

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / 'dist' / 'Event-Based-Studio'
    executable = folder / 'Event-Based-Studio.exe'
    archive = CArchiveReader(str(executable))
    modules = archive.open_embedded_archive('PYZ.pyz')
    sources = {}
    for source in sorted((ROOT / 'event_studio').rglob('*.py')):
        if source.name == '__main__.py':
            continue  # Development launcher; the EXE uses desktop_entry instead.
        name = '.'.join(source.relative_to(ROOT).with_suffix('').parts).removesuffix('.__init__')
        assert name in modules.toc, f'Missing app module: {name}'
        actual = modules.extract(name)
        assert actual == compile(source.read_bytes(), actual.co_filename, 'exec', dont_inherit=True, optimize=0), f'Stale module: {name}'
        sources[str(source.relative_to(ROOT))] = hashlib.sha256(source.read_bytes()).hexdigest()
    import marshal
    entry = ROOT / 'scripts' / 'desktop_entry.py'
    actual = marshal.loads(archive.extract('desktop_entry'))
    assert actual == compile(entry.read_bytes(), actual.co_filename, 'exec', dont_inherit=True, optimize=0), 'Stale packaged launcher'
    assets = 0
    for source in (ROOT / 'event_studio' / 'assets').rglob('*'):
        if source.is_file():
            target = folder / '_internal' / source.relative_to(ROOT)
            assert target.read_bytes() == source.read_bytes(), f'Stale/missing asset: {source.name}'
            assets += 1
    info = json.loads((folder / 'BUILD-INFO.json').read_text())
    app_zip = ROOT / 'dist' / f"Event-Based-Studio-{info['version']}-windows-x64-preview.zip"
    with zipfile.ZipFile(app_zip) as bundle:
        for source in folder.rglob('*'):
            if source.is_file():
                assert bundle.read(source.relative_to(folder.parent).as_posix()) == source.read_bytes(), f'Stale app ZIP member: {source}'
    website = ROOT / 'artifacts' / 'Event-Based-Studio-Cloudflare-Website.zip'
    with zipfile.ZipFile(website) as bundle:
        manifest = json.loads(bundle.read('downloads/manifest.json'))['application']
        digest = hashlib.sha256()
        size = 0
        for part in manifest['parts']:
            data = bundle.read(part)
            digest.update(data)
            size += len(data)
        app_hash = hashlib.sha256(app_zip.read_bytes()).hexdigest()
        assert digest.hexdigest() == manifest['sha256'] == app_hash, 'Website ZIP contains a different app'
        assert size == manifest['size'] == app_zip.stat().st_size
    report = {'version': info['version'], 'modules_verified': len(sources),
              'assets_verified': assets, 'launcher_verified': True,
              'application_sha256': app_hash, 'workspace_sources': sources,
              'website_zip_sha256': hashlib.sha256(website.read_bytes()).hexdigest(),
              'live_deployment_verified': False}
    output = ROOT / 'artifacts' / 'workspace-download-verification.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'PASS: {len(sources)} app modules, launcher, {assets} assets, app ZIP, and website ZIP match the workspace.')
    print(f'Report: {output}')


if __name__ == '__main__':
    main()
