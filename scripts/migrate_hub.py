#!/usr/bin/env python3
"""One-time, idempotent source migration. Never pushes or merges anything."""
from __future__ import annotations
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 'd293f7e15fbc7b20904a0eaa045ddf2f6f515fc8'
MOVES = {
    'QR-seek-app-redirect.html': 'Apps/Seek/QR-seek-app-redirect.html',
    'road_trip_atlas.html': 'Web-Tools/County-Map-Maker/road_trip_atlas.html',
    'TSC_Logo_Generator_v1_2.html': 'TSC-Work/Logo-Generator/TSC_Logo_Generator_v1_2.html',
    'canvas_banner.html': 'GPT-Tools/Canvas-Banner/canvas_banner.html',
    'Articles/Spandrels1979.html': 'Articles/Spandrels-1979/Spandrels1979.html',
    'ducks.html': 'Duck-Game/ducks.html',
    'ducks_2.html': 'Duck-Game/ducks_2.html',
    'duck-quack.wav': 'Duck-Game/duck-quack.wav',
    'duck-quack.mp3': 'Duck-Game/duck-quack.mp3',
    'date_time_picker_comparison.html': 'Experiments/date_time_picker_comparison.html',
    'switch_1_pro_controller_shell_swap.html': 'Guides/Switch-Pro-Controller/switch_1_pro_controller_shell_swap.html',
    'campus-map-demo.zip': 'Archives/Source-Packages/campus-map-demo.zip',
}
for version in ['1_5', '1_8', '1_9', '2_0', '2_1', '2_1_5', '2_1_8', '2_2_0']:
    name = f'TSC_OTS_Generator_v{version}.html'
    MOVES[name] = f'TSC-Work/OTS-Generator/{name}'
for number in (1, 2, 3):
    name = f'Figure{number}_Spandrels1979.jpg'
    MOVES[f'Articles/{name}'] = f'Articles/Spandrels-1979/{name}'


def git(*args: str) -> bytes:
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main() -> None:
    branch = git('branch', '--show-current').decode().strip()
    if branch != 'reorganize-hub':
        raise RuntimeError(f'Refusing migration outside reorganize-hub: {branch}')
    rows = []
    # Preflight every source before changing anything.
    for old, new in MOVES.items():
        original = git('show', f'{BASELINE}:{old}')
        source, target = ROOT / old, ROOT / new
        if source.exists() and target.exists():
            raise RuntimeError(f'Both paths exist: {old} / {new}')
        existing = target if target.exists() else source
        if not existing.is_file() or existing.read_bytes() != original:
            raise RuntimeError(f'Source differs from audited baseline: {old}')
        rows.append({'from': old, 'to': new, 'sha256': hashlib.sha256(original).hexdigest(),
                     'git_blob': git('rev-parse', f'{BASELINE}:{old}').decode().strip()})
    for row in rows:
        source, target = ROOT / row['from'], ROOT / row['to']
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == row['sha256']
        print(f'PRESERVED {row["from"]} -> {row["to"]}', flush=True)
    deleted = []
    for name in ['Articles/File', 'Experiments/A']:
        target = ROOT / name
        if target.exists():
            if target.read_bytes().strip():
                raise RuntimeError(f'Placeholder contains content: {name}')
            target.unlink()
        deleted.append(name)
    extracted = []
    with zipfile.ZipFile(ROOT / MOVES['campus-map-demo.zip']) as archive:
        if archive.testzip():
            raise RuntimeError('Campus archive failed CRC check')
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in info.filename:
                raise RuntimeError(f'Unsafe ZIP member: {info.filename}')
            if info.is_dir():
                continue
            if path.parts[0] != 'campus-map-demo' or ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise RuntimeError(f'Unexpected ZIP member: {info.filename}')
            destination = Path('Experiments/Campus-Map').joinpath(*path.parts[1:])
            data = archive.read(info)
            target = ROOT / destination
            if target.exists() and target.read_bytes() != data:
                raise RuntimeError(f'Extraction would overwrite modified file: {destination}')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            extracted.append({'member': info.filename, 'path': destination.as_posix(),
                              'sha256': hashlib.sha256(data).hexdigest()})
            print(f'EXTRACTED {destination} ({len(data)} bytes)', flush=True)
    assert (ROOT / 'Experiments/Campus-Map/index.html').is_file()
    (ROOT / 'docs').mkdir(exist_ok=True)
    record = {'baseline_commit': BASELINE, 'moves': rows, 'removed_empty_placeholders': deleted,
              'extracted': extracted, 'notes': 'All moved content is byte-identical to the baseline. No application fixes or version relabeling.'}
    (ROOT / 'docs/migration_map.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    (ROOT / 'hub_redirects.json').write_text(json.dumps(MOVES, indent=2) + '\n', encoding='utf-8')
    print(f'PASS: {len(rows)} byte-identical moves, {len(extracted)} extracted files; no push or merge performed.')


if __name__ == '__main__':
    main()
