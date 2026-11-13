"""Build an APU archive from a directory of ready-to-run plugin files."""

import argparse
import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from module.api.plugin_service import PluginService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_dir() or output.suffix.lower() != '.apu' or output.is_relative_to(source):
        parser.error('source must be a directory and output must be an .apu outside it')
    archive_bytes = io.BytesIO()
    with ZipFile(archive_bytes, 'w', compression=ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                parser.error(f'symlink is not allowed: {path}')
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
        if not (source / 'apu.js').exists():
            bridge = Path(__file__).resolve().parents[1] / 'frontend' / 'plugin-sdk' / 'bridge.js'
            archive.write(bridge, 'apu.js')
    data = archive_bytes.getvalue()
    try:
        PluginService.validate_package(data)
    except ValueError as error:
        parser.error(str(error))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    print(output)


if __name__ == '__main__':
    main()
