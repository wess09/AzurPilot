"""从人工核实的实机等级裁剪生成模板，不使用 OCR 结果作为训练标签。"""
import json
from pathlib import Path

import numpy as np
from PIL import Image

from module.base.utils import extract_white_letters
from module.runtime.mind_level import prepare_level
from module.storage.amount_glyphs import GLYPH_HEIGHT, GLYPH_WIDTH


def build():
    root = Path(__file__).parents[1]
    fixture = root / 'tests/fixtures'
    cases = json.loads((fixture / 'mind_levels.json').read_text(encoding='utf-8'))
    pixels = np.array(Image.open(fixture / 'mind_levels.png').convert('RGB'))
    first = pixels[:32, 4 * 64:5 * 64]
    prefix = extract_white_letters(first, threshold=128)[8:27, 7:26] < 120
    prefix[:, 0] = False
    samples = [[] for _ in range(10)]
    for page, case in enumerate(cases):
        if not case['training']:
            continue
        for index, value in enumerate(case['levels']):
            row, col = divmod(index, 7)
            raw = pixels[(page * 3 + row) * 32:(page * 3 + row + 1) * 32, col * 64:(col + 1) * 64]
            glyphs, _, _ = prepare_level(raw, prefix)
            if len(glyphs) != len(str(value)):
                raise ValueError(f'{case["page"]} 第 {index + 1} 格等级锚点不符合人工标签')
            for glyph, digit in zip(glyphs, str(value)):
                # 保留不同采样相位，完全相同的字形只存一次。
                if not any(np.array_equal(glyph, previous) for previous in samples[int(digit)]):
                    samples[int(digit)].append(glyph)
    if any(not variants for variants in samples):
        raise ValueError('训练样本没有覆盖全部十种数字')
    atlas = np.full((max(map(len, samples)) * GLYPH_HEIGHT, 10 * GLYPH_WIDTH), 255, np.uint8)
    for digit, variants in enumerate(samples):
        for index, glyph in enumerate(variants):
            atlas[index * GLYPH_HEIGHT:(index + 1) * GLYPH_HEIGHT,
                  digit * GLYPH_WIDTH:(digit + 1) * GLYPH_WIDTH] = glyph
    Image.fromarray(atlas).save(root / 'assets/ship/dock_level_digits.png')
    Image.fromarray(255 - prefix.astype(np.uint8) * 255).save(root / 'assets/ship/dock_level_prefix.png')
    from module.retire.dock import CARD_GRIDS
    from module.retire.scanner import FleetScanner
    from module.runtime.mind_recognition import grid_rows
    screen = np.array(Image.open(fixture / 'mind_dock_fleet_priority.png').convert('RGB'))
    y, x = grid_rows(screen)[0], round(float(CARD_GRIDS.origin[0]))
    label = FleetScanner().pre_process(screen[y + 139:y + 159, x:x + 30])[3:16, 3:30]
    Image.fromarray(label).save(root / 'assets/ship/dock_fleet_label.png')


if __name__ == '__main__':
    build()
