"""
按钮区域图像编辑器 —— button_extract.py 的逆向工具。

对指定的按钮图片按给定区域坐标进行处理，然后运行 button_extract.py 即可重新生成
正确的 area/color/button 值。

处理规则：
  - TEMPLATE_* 开头的图片：裁剪出区域内的像素，另存为小图（模板匹配用）
  - 非 TEMPLATE 的普通 Button 图片：将区域外的像素全部置黑 (0,0,0)，
    保留区域内像素不变。这样 button_extract.py 的 get_bbox() 会自动检测到正确的边界框。

使用方法：
  1. 在下面的 TASKS 列表中填写要处理的图片路径和区域坐标
  2. 运行: python dev_tools/button_region_editor.py
  3. 处理完毕后，运行 button_extract.py 重新生成 assets.py：
     uv run python -m dev_tools.button_extract
"""

import os
import sys

import numpy as np
from PIL import Image

# ============================================================
# 【在此处填写要处理的图片路径和目标区域坐标】
# 格式: ("图片路径（相对项目根目录）", (x1, y1, x2, y2))
# ============================================================
TASKS = [
    # ("./assets/cn/island_daily_order/TEMPLATE_CHEESE.png", (905,335,950,380)),
    # ("./assets/cn/island_daily_order/TEMPLATE_TOFU.png", (905,255,950,300)),
    ("./assets/cn/island_business/TEMPLATE_BUSINESS_LIST_SHOP_JUU_COFFEE.png",      (219, 533,  326, 559)),
]


def process_button_image(img_path, area):
    """
    处理普通 Button 图片：
    - 将区域 (x1,y1,x2,y2) 之外的像素全部置黑 (0,0,0)
    - 区域内像素保持不变
    - 图片尺寸保持 1280x720 不变
    """
    print(f"  [Button] 处理: {os.path.basename(img_path)}, 区域={area}")

    img = Image.open(img_path).convert("RGB")
    arr = np.array(img, dtype=np.uint8)

    if arr.shape[:2] != (720, 1280):
        print(f"  [WARN] 图片尺寸不是 1280x720，实际为 {arr.shape[1]}x{arr.shape[0]}")

    x1, y1, x2, y2 = area
    # 创建全黑画布
    black = np.zeros_like(arr)
    # 只复制区域内像素
    black[y1:y2, x1:x2] = arr[y1:y2, x1:x2]

    # 保存
    result = Image.fromarray(black, "RGB")
    result.save(img_path)
    print(f"  [OK] 已保存（区域外已置黑）: {img_path}")
    return True


def process_template_image(img_path, area):
    """
    处理 TEMPLATE 图片：
    - 从原图中裁剪出 area 区域
    - 另存为小图（只包含区域内像素）
    """
    print(f"  [Template] 处理: {os.path.basename(img_path)}, 区域={area}")

    img = Image.open(img_path).convert("RGB")
    x1, y1, x2, y2 = area
    # 裁剪区域
    cropped = img.crop((x1, y1, x2, y2))

    cropped.save(img_path)
    w, h = x2 - x1, y2 - y1
    print(f"  [OK] 已保存（裁剪为 {w}x{h}）: {img_path}")
    return True


def run():
    print("=" * 60)
    print("按钮区域图像编辑器 - button_extract 逆向工具")
    print("=" * 60)

    if not TASKS:
        print("[ERR] TASKS 列表为空，请先在脚本顶部填写要处理的图片路径和区域坐标。")
        sys.exit(1)

    # 切换到项目根目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    os.chdir(project_root)
    print(f"项目根目录: {project_root}")
    print()

    success_count = 0
    error_count = 0

    for img_path, area in TASKS:
        # 校验区域坐标
        x1, y1, x2, y2 = area
        if x1 < 0 or y1 < 0 or x2 > 1280 or y2 > 720 or x1 >= x2 or y1 >= y2:
            print(f"  [ERR] 无效区域坐标 {area}（图片尺寸 1280x720）: {img_path}")
            error_count += 1
            continue

        # 检查图片是否存在
        abs_path = os.path.join(project_root, img_path)
        if not os.path.exists(abs_path):
            print(f"  [ERR] 文件不存在: {img_path}")
            error_count += 1
            continue

        # 根据文件名判断类型
        basename = os.path.basename(img_path)
        if basename.startswith("TEMPLATE_"):
            ok = process_template_image(abs_path, area)
        else:
            ok = process_button_image(abs_path, area)

        if ok:
            success_count += 1
        else:
            error_count += 1

    print()
    print("=" * 60)
    print(f"处理完成：成功 {success_count} 个，失败 {error_count} 个")
    if success_count > 0:
        print()
        print("下一步：运行 button_extract.py 重新生成 assets.py：")
        print("  uv run python -m dev_tools.button_extract")
    print("=" * 60)


if __name__ == "__main__":
    run()
