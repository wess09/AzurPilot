import random
import re

import cv2
import numpy as np
from PIL import Image

REGEX_NODE = re.compile(r'(-?[A-Za-z]+)(-?\d+)')
TEMPLATE_MATCH_NON_NATIVE_720P = False
TEMPLATE_MATCH_NON_NATIVE_720P_THRESHOLD = 0.75
TEMPLATE_MATCH_NON_NATIVE_720P_RESOLUTION = (1280, 720)


def set_template_match_non_native_720p(enabled, resolution=(1280, 720)):
    global TEMPLATE_MATCH_NON_NATIVE_720P, TEMPLATE_MATCH_NON_NATIVE_720P_RESOLUTION
    TEMPLATE_MATCH_NON_NATIVE_720P = bool(enabled)
    TEMPLATE_MATCH_NON_NATIVE_720P_RESOLUTION = resolution


def lower_template_match_similarity(similarity):
    """
    对非原生 720p 截图放宽模板匹配阈值。

    当截图不是以 1280x720 原始分辨率捕获时，将严格阈值限制在 0.75。

    Args:
        similarity: 0~1 范围的 cv2.TM_CCOEFF_NORMED 阈值。

    Returns:
        float: 调整后的相似度阈值。
    """
    similarity = float(similarity)
    if TEMPLATE_MATCH_NON_NATIVE_720P:
        return min(similarity, TEMPLATE_MATCH_NON_NATIVE_720P_THRESHOLD)
    return similarity


def random_normal_distribution_int(a, b, n=3):
    """
    在区间内生成正态分布的随机整数。
    使用多个随机数的平均值来模拟正态分布。

    Args:
        a (int): 区间最小值。
        b (int): 区间最大值。
        n (int): 模拟时使用的随机数数量，默认为 3。

    Returns:
        int: 正态分布随机整数。
    """
    a = round(a)
    b = round(b)
    if a < b:
        total = 0
        for _ in range(n):
            total += random.randint(a, b)
        return round(total / n)
    else:
        return b


def random_rectangle_point(area, n=3):
    """在区域内随机选取一个点。

    Args:
        area: (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
        n (int): 模拟时使用的随机数数量，默认为 3。

    Returns:
        tuple[int]: (x, y) 坐标。
    """
    x = random_normal_distribution_int(area[0], area[2], n=n)
    y = random_normal_distribution_int(area[1], area[3], n=n)
    return x, y


def random_rectangle_vector(vector, box, random_range=(0, 0, 0, 0), padding=15):
    """在区域内随机放置一个向量。

    Args:
        vector: 向量 (x, y)。
        box: 区域 (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
        random_range (tuple): 向量的随机偏移范围 (x_min, y_min, x_max, y_max)。
        padding (int): 内边距。

    Returns:
        tuple[int], tuple[int]: 起点和终点坐标。
    """
    vector = np.array(vector) + random_rectangle_point(random_range)
    vector = np.round(vector).astype(int)
    half_vector = np.round(vector / 2).astype(int)
    box = np.array(box) + np.append(np.abs(half_vector) + padding, -np.abs(half_vector) - padding)
    center = random_rectangle_point(box)
    start_point = center - half_vector
    end_point = start_point + vector
    return tuple(start_point), tuple(end_point)


def random_rectangle_vector_opted(
        vector, box, random_range=(0, 0, 0, 0), padding=15, whitelist_area=None, blacklist_area=None):
    """
    在区域内随机放置一个向量（带白名单/黑名单过滤）。

    当模拟器或游戏卡住时，滑动操作可能被当作点击处理（点击滑动路径终点）。
    为防止这种情况，需要对随机结果进行过滤。

    Args:
        vector: 向量 (x, y)。
        box: 区域 (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
        random_range (tuple): 向量的随机偏移范围 (x_min, y_min, x_max, y_max)。
        padding (int): 内边距。
        whitelist_area: 安全点击区域列表，滑动路径将在此范围内结束。
        blacklist_area: 当白名单区域无法满足当前向量时使用黑名单。
            排除终点在黑名单区域内的随机路径。

    Returns:
        tuple[int], tuple[int]: 起点和终点坐标。
    """
    vector = np.array(vector) + random_rectangle_point(random_range)
    vector = np.round(vector).astype(int)
    half_vector = np.round(vector / 2).astype(int)
    box_pad = np.array(box) + np.append(np.abs(half_vector) + padding, -np.abs(half_vector) - padding)
    box_pad = area_offset(box_pad, half_vector)
    segment = int(np.linalg.norm(vector) // 70) + 1

    def in_blacklist(end):
        if not blacklist_area:
            return False
        for x in range(segment + 1):
            point = - vector * x / segment + end
            for area in blacklist_area:
                if point_in_area(point, area, threshold=0):
                    return True
        return False

    if whitelist_area:
        for area in whitelist_area:
            area = area_limit(area, box_pad)
            if all([x > 0 for x in area_size(area)]):
                end_point = random_rectangle_point(area)
                for _ in range(10):
                    if in_blacklist(end_point):
                        continue
                    return point_limit(end_point - vector, box), point_limit(end_point, box)

    for _ in range(100):
        end_point = random_rectangle_point(box_pad)
        if in_blacklist(end_point):
            continue
        return point_limit(end_point - vector, box), point_limit(end_point, box)

    end_point = random_rectangle_point(box_pad)
    return point_limit(end_point - vector, box), point_limit(end_point, box)


def random_line_segments(p1, p2, n, random_range=(0, 0, 0, 0)):
    """将线段分割为多段。

    Args:
        p1: 起点 (x, y)。
        p2: 终点 (x, y)。
        n: 分割段数。
        random_range: 各点的随机偏移范围。

    Returns:
        list[tuple]: 分割点列表 [(x0, y0), (x1, y1), (x2, y2)]。
    """
    return [tuple((((n - index) * p1 + index * p2) / n).astype(int) + random_rectangle_point(random_range))
            for index in range(0, n + 1)]


def ensure_time(second, n=3, precision=3):
    """确保返回有效的时间值。

    Args:
        second (int, float, tuple): 时间值，如 10、(10, 30)、'10, 30'。
        n (int): 模拟时使用的随机数数量，默认为 3。
        precision (int): 小数精度。

    Returns:
        float: 处理后的时间值。
    """
    if isinstance(second, tuple):
        multiply = 10 ** precision
        result = random_normal_distribution_int(second[0] * multiply, second[1] * multiply, n) / multiply
        return round(result, precision)
    elif isinstance(second, str):
        if ',' in second:
            lower, upper = second.replace(' ', '').split(',')
            lower, upper = int(lower), int(upper)
            return ensure_time((lower, upper), n=n, precision=precision)
        if '-' in second:
            lower, upper = second.replace(' ', '').split('-')
            lower, upper = int(lower), int(upper)
            return ensure_time((lower, upper), n=n, precision=precision)
        else:
            return int(second)
    else:
        return second


def ensure_int(*args):
    """
    将所有元素转换为整数。
    保持与嵌套对象相同的结构。

    Args:
        *args: 任意参数。

    Returns:
        list: 转换后的整数列表。
    """

    def to_int(item):
        try:
            return int(item)
        except TypeError:
            result = [to_int(i) for i in item]
            if len(result) == 1:
                result = result[0]
            return result

    return to_int(args)


def area_offset(area, offset):
    """
    平移区域。

    Args:
        area: (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
        offset: 偏移量 (x, y)。

    Returns:
        tuple: (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
    """
    upper_left_x, upper_left_y, bottom_right_x, bottom_right_y = area
    x, y = offset
    return upper_left_x + x, upper_left_y + y, bottom_right_x + x, bottom_right_y + y


def area_pad(area, pad=10):
    """
    对区域进行内缩偏移。

    Args:
        area: (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
        pad (int): 内缩像素值。

    Returns:
        tuple: (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
    """
    upper_left_x, upper_left_y, bottom_right_x, bottom_right_y = area
    return upper_left_x + pad, upper_left_y + pad, bottom_right_x - pad, bottom_right_y - pad


def limit_in(x, lower, upper):
    """
    将 x 限制在 [lower, upper] 范围内。

    Args:
        x: 待限制的值。
        lower: 下限。
        upper: 上限。

    Returns:
        int, float: 限制后的值。
    """
    return max(min(x, upper), lower)


def area_limit(area1, area2):
    """
    将一个区域限制在另一个区域内。

    Args:
        area1: 待限制的区域 (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
        area2: 限制边界区域 (左上角 x, 左上角 y, 右下角 x, 右下角 y)。

    Returns:
        tuple: (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
    """
    x_lower, y_lower, x_upper, y_upper = area2
    return (
        limit_in(area1[0], x_lower, x_upper),
        limit_in(area1[1], y_lower, y_upper),
        limit_in(area1[2], x_lower, x_upper),
        limit_in(area1[3], y_lower, y_upper),
    )


def area_size(area):
    """
    计算区域的尺寸（宽高）。

    Args:
        area: (左上角 x, 左上角 y, 右下角 x, 右下角 y)。

    Returns:
        tuple: (宽度, 高度)。
    """
    return (
        max(area[2] - area[0], 0),
        max(area[3] - area[1], 0)
    )


def point_limit(point, area):
    """
    将点限制在区域内。

    Args:
        point: 点坐标 (x, y)。
        area: 限制区域 (左上角 x, 左上角 y, 右下角 x, 右下角 y)。

    Returns:
        tuple: 限制后的坐标 (x, y)。
    """
    return (
        limit_in(point[0], area[0], area[2]),
        limit_in(point[1], area[1], area[3])
    )


def point_in_area(point, area, threshold=5):
    """判断点是否在区域内。

    Args:
        point: 点坐标 (x, y)。
        area: 区域 (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
        threshold (int): 容差阈值。

    Returns:
        bool: 点在区域内返回 True。
    """
    return area[0] - threshold < point[0] < area[2] + threshold and area[1] - threshold < point[1] < area[3] + threshold


def area_in_area(area1, area2, threshold=5):
    """判断区域1是否完全在区域2内。

    Args:
        area1: 区域1 (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
        area2: 区域2 (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
        threshold (int): 容差阈值。

    Returns:
        bool: 区域1完全在区域2内返回 True。
    """
    return area2[0] - threshold <= area1[0] \
           and area2[1] - threshold <= area1[1] \
           and area1[2] <= area2[2] + threshold \
           and area1[3] <= area2[3] + threshold


def area_cross_area(area1, area2, threshold=5):
    """判断两个区域是否相交。

    Args:
        area1: 区域1 (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
        area2: 区域2 (左上角 x, 左上角 y, 右下角 x, 右下角 y)。
        threshold (int): 容差阈值。

    Returns:
        bool: 两区域相交返回 True。
    """
    # https://www.yiiven.cn/rect-is-intersection.html
    xa1, ya1, xa2, ya2 = area1
    xb1, yb1, xb2, yb2 = area2
    return abs(xb2 + xb1 - xa2 - xa1) <= xa2 - xa1 + xb2 - xb1 + threshold * 2 \
           and abs(yb2 + yb1 - ya2 - ya1) <= ya2 - ya1 + yb2 - yb1 + threshold * 2


def float2str(n, decimal=3):
    """将浮点数转换为固定小数位的字符串。

    Args:
        n (float): 待转换的浮点数。
        decimal (int): 小数位数。

    Returns:
        str: 格式化后的字符串。
    """
    return str(round(n, decimal)).ljust(decimal + 2, "0")


def point2str(x, y, length=4):
    """将坐标点转换为右对齐的字符串。

    Args:
        x (int, float): x 坐标。
        y (int, float): y 坐标。
        length (int): 对齐长度。

    Returns:
        str: 右对齐的坐标字符串，如 '( 100,  80)'。
    """
    return '(%s, %s)' % (str(int(x)).rjust(length), str(int(y)).rjust(length))


def col2name(col):
    """
    将零索引的列号转换为 Excel 风格的列名字符串。

    Args:
       col (int): 列号（从 0 开始）。

    Returns:
        str: 列名字符串。

    Examples:
        0 -> A, 3 -> D, 35 -> AJ, -1 -> -A
    """

    col_neg = col < 0
    if col_neg:
        col_num = -col
    else:
        col_num = col + 1  # 转换为 1 索引
    col_str = ''

    while col_num:
        # 余数范围 1..26
        remainder = col_num % 26

        if remainder == 0:
            remainder = 26

        # 将余数转换为字符
        col_letter = chr(remainder + 64)

        # 从右到左累加列字母
        col_str = col_letter + col_str

        # 获取下一个数量级
        col_num = int((col_num - 1) / 26)

    if col_neg:
        return '-' + col_str
    else:
        return col_str


def name2col(col_str):
    """
    将 A1 风格的列名字符串转换为零索引的列号。

    Args:
       col_str (str): A1 风格的列名字符串。

    Returns:
        int: 零索引的列号。
    """
    # 将 26 进制列名字符串转换为数字
    expn = 0
    col = 0
    col_neg = col_str.startswith('-')
    col_str = col_str.strip('-').upper()

    for char in reversed(col_str):
        col += (ord(char) - 64) * (26 ** expn)
        expn += 1

    if col_neg:
        return -col
    else:
        return col - 1  # 从 1 索引转换为 0 索引


def node2location(node):
    """
    将网格节点字符串转换为位置元组。参见 location2node()。

    Args:
        node (str): 网格节点字符串，如 'E3'。

    Returns:
        tuple[int]: 位置元组，如 (4, 2)。
    """
    res = REGEX_NODE.search(node)
    if res:
        x, y = res.group(1), res.group(2)
        y = int(y)
        if y > 0:
            y -= 1
        return name2col(x), y
    else:
        # 兜底方案
        return ord(node[0]) % 32 - 1, int(node[1:]) - 1


def location2node(location):
    """
    将位置元组转换为 Excel 风格的网格节点字符串。
    支持负值。

         -2   -1    0    1    2    3
    -2 -B-2 -A-2  A-2  B-2  C-2  D-2
    -1 -B-1 -A-1  A-1  B-1  C-1  D-1
     0  -B1  -A1   A1   B1   C1   D1
     1  -B2  -A2   A2   B2   C2   D2
     2  -B3  -A3   A3   B3   C3   D3
     3  -B4  -A4   A4   B4   C4   D4

    Args:
        location (tuple[int]): 位置元组 (x, y)。

    Returns:
        str: 网格节点字符串。
    """
    x, y = location
    if y >= 0:
        y += 1
    return col2name(x) + str(y)


def xywh2xyxy(area):
    """将 (x, y, 宽度, 高度) 格式转换为 (x1, y1, x2, y2) 格式。"""
    x, y, w, h = area
    return x, y, x + w, y + h


def xyxy2xywh(area):
    """将 (x1, y1, x2, y2) 格式转换为 (x, y, 宽度, 高度) 格式。"""
    x1, y1, x2, y2 = area
    return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)


def load_image(file, area=None):
    """
    加载图像并移除 alpha 通道，类似 pillow 的行为。

    Args:
        file (str): 图像文件路径。
        area (tuple): 裁剪区域。

    Returns:
        np.ndarray: 图像数组。
    """
    # 始终记得关闭 Image 对象
    with Image.open(file) as f:
        if area is not None:
            f = f.crop(area)

        image = np.array(f)

    channel = image_channel(image)
    if channel == 4:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)

    return image


def save_image(image, file):
    """
    保存图像，类似 pillow 的行为。

    Args:
        image (np.ndarray): 图像数组。
        file (str): 保存路径。
    """
    # image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    # cv2.imwrite(file, image)
    Image.fromarray(image).save(file)


def copy_image(src):
    """
    等效于 image.copy() 但速度略快。

    复制 1280*720*3 图像的时间开销：
        image.copy()      0.743ms
        copy_image(image) 0.639ms

    Args:
        src: 源图像数组。

    Returns:
        np.ndarray: 图像副本。
    """
    dst = np.empty_like(src)
    cv2.copyTo(src, None, dst)
    return dst


def crop(image, area, copy=True):
    """
    裁剪图像，类似 pillow 的 crop 行为，适用于 opencv/numpy。
    当裁剪区域超出图像边界时，使用黑色填充。

    Args:
        image (np.ndarray): 图像数组。
        area: 裁剪区域 (x1, y1, x2, y2)。
        copy (bool): 是否复制裁剪结果。

    Returns:
        np.ndarray: 裁剪后的图像数组。
    """
    # map(round, area)
    x1, y1, x2, y2 = area
    x1 = round(x1)
    y1 = round(y1)
    x2 = round(x2)
    y2 = round(y2)
    # h, w = image.shape[:2]
    shape = image.shape
    h = shape[0]
    w = shape[1]
    # 上, 下, 左, 右
    # border = np.maximum((0 - y1, y2 - h, 0 - x1, x2 - w), 0)
    overflow = False
    if y1 >= 0:
        top = 0
        if y1 >= h:
            overflow = True
    else:
        top = -y1
    if y2 > h:
        bottom = y2 - h
    else:
        bottom = 0
        if y2 <= 0:
            overflow = True
    if x1 >= 0:
        left = 0
        if x1 >= w:
            overflow = True
    else:
        left = -x1
    if x2 > w:
        right = x2 - w
    else:
        right = 0
        if x2 <= 0:
            overflow = True
    # 如果溢出，返回空图像
    if overflow:
        if len(shape) == 2:
            size = (y2 - y1, x2 - x1)
        else:
            size = (y2 - y1, x2 - x1, shape[2])
        return np.zeros(size, dtype=image.dtype)
    # x1, y1, x2, y2 = np.maximum((x1, y1, x2, y2), 0)
    if x1 < 0:
        x1 = 0
    if y1 < 0:
        y1 = 0
    if x2 < 0:
        x2 = 0
    if y2 < 0:
        y2 = 0
    # 裁剪图像
    image = image[y1:y2, x1:x2]
    # 如果需要填充边界
    if top or bottom or left or right:
        if len(shape) == 2:
            value = 0
        else:
            value = tuple(0 for _ in range(image.shape[2]))
        return cv2.copyMakeBorder(image, top, bottom, left, right, borderType=cv2.BORDER_CONSTANT, value=value)
    elif copy:
        return copy_image(image)
    else:
        return image


def resize(image, size):
    """
    调整图像大小，类似 pillow 的 image.resize()，使用 opencv 实现。
    pillow 默认使用 PIL.Image.NEAREST 插值。

    Args:
        image (np.ndarray): 图像数组。
        size: 目标大小 (宽, 高)。

    Returns:
        np.ndarray: 调整大小后的图像数组。
    """
    return cv2.resize(image, size, interpolation=cv2.INTER_NEAREST)


def image_channel(image):
    """获取图像的通道数。

    Args:
        image (np.ndarray): 图像数组。

    Returns:
        int: 0 表示灰度图，3 表示 RGB 图像。
    """
    return image.shape[2] if len(image.shape) == 3 else 0


def image_size(image):
    """获取图像的尺寸。

    Args:
        image (np.ndarray): 图像数组。

    Returns:
        int, int: 宽度和高度。
    """
    shape = image.shape
    return shape[1], shape[0]


def image_paste(image, background, origin):
    """
    将图像粘贴到背景上。
    此方法不返回值，而是直接更新 background 数组。

    Args:
        image: 待粘贴的图像数组。
        background: 背景图像数组。
        origin: 粘贴位置的左上角坐标 (x, y)。
    """
    x, y = origin
    w, h = image_size(image)
    background[y:y + h, x:x + w] = image


def rgb2gray(image):
    """
    将 RGB 图像转换为灰度图。
    gray = ( MAX(r, g, b) + MIN(r, g, b)) / 2

    Args:
        image (np.ndarray): 形状 (height, width, channel)。

    Returns:
        np.ndarray: 灰度图，形状 (height, width)。
    """
    # r, g, b = cv2.split(image)
    # return cv2.add(
    #     cv2.multiply(cv2.max(cv2.max(r, g), b), 0.5),
    #     cv2.multiply(cv2.min(cv2.min(r, g), b), 0.5)
    # )
    r, g, b = cv2.split(image)
    maximum = cv2.max(r, g)
    cv2.min(r, g, dst=r)
    cv2.max(maximum, b, dst=maximum)
    cv2.min(r, b, dst=r)
    # minimum = r
    cv2.convertScaleAbs(maximum, alpha=0.5, dst=maximum)
    cv2.convertScaleAbs(r, alpha=0.5, dst=r)
    cv2.add(maximum, r, dst=maximum)
    return maximum


def rgb2hsv(image):
    """
    将 RGB 色彩空间转换为 HSV 色彩空间。
    HSV 即色相、饱和度、明度。

    Args:
        image (np.ndarray): 形状 (height, width, channel)。

    Returns:
        np.ndarray: 色相 (0~360)、饱和度 (0~100)、明度 (0~100)。
    """
    image = cv2.cvtColor(image, cv2.COLOR_RGB2HSV).astype(float)
    cv2.multiply(image, (360 / 180, 100 / 255, 100 / 255), dst=image)
    return image


def rgb2yuv(image):
    """
    将 RGB 转换为 YUV 色彩空间。

    Args:
        image (np.ndarray): 形状 (height, width, channel)。

    Returns:
        np.ndarray: YUV 图像。
    """
    image = cv2.cvtColor(image, cv2.COLOR_RGB2YUV)
    return image


def rgb2luma(image):
    """
    将 RGB 转换为 YUV 色彩空间的 Y 通道（亮度）。

    Args:
        image (np.ndarray): 形状 (height, width, channel)。

    Returns:
        np.ndarray: 亮度通道，形状 (height, width)。
    """
    image = cv2.cvtColor(image, cv2.COLOR_RGB2YUV)
    luma, _, _ = cv2.split(image)
    return luma


def get_color(image, area):
    """计算图像指定区域的平均颜色。

    Args:
        image (np.ndarray): 截图。
        area (tuple): (左上角 x, 左上角 y, 右下角 x, 右下角 y)。

    Returns:
        tuple: (r, g, b) 平均颜色值。
    """
    temp = crop(image, area, copy=False)
    color = cv2.mean(temp)
    return color[:3]


class ImageNotSupported(Exception):
    """当无法对图像执行计算操作时抛出此异常。"""
    pass


def get_bbox(image, threshold=0):
    """
    获取图像内容的外接边界框。
    pillow getbbox() 的 opencv 实现。

    Args:
        image (np.ndarray): 图像数组。
        threshold (int): 颜色阈值。
            color > threshold 视为内容，color <= threshold 视为背景。

    Returns:
        tuple[int, int, int, int]: 边界框区域 (x1, y1, x2, y2)。

    Raises:
        ImageNotSupported: 获取边界框失败时抛出。
    """
    channel = image_channel(image)
    # 转换为灰度图
    if channel == 3:
        # RGB
        mask = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        cv2.threshold(mask, threshold, 255, cv2.THRESH_BINARY, dst=mask)
    elif channel == 0:
        # 灰度图
        _, mask = cv2.threshold(image, threshold, 255, cv2.THRESH_BINARY)
    elif channel == 4:
        # RGBA
        mask = cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
        cv2.threshold(mask, threshold, 255, cv2.THRESH_BINARY, dst=mask)
    else:
        raise ImageNotSupported(f'shape={image.shape}')

    # 查找边界框
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_y, min_x = mask.shape
    max_x = 0
    max_y = 0
    # 全黑图像
    if not contours:
        raise ImageNotSupported(f'Cannot get bbox from a pure black image')
    for contour in contours:
        # x, y, w, h
        x1, y1, x2, y2 = cv2.boundingRect(contour)
        x2 += x1
        y2 += y1
        if x1 < min_x:
            min_x = x1
        if y1 < min_y:
            min_y = y1
        if x2 > max_x:
            max_x = x2
        if y2 > max_y:
            max_y = y2
    if min_x < max_x and min_y < max_y:
        return min_x, min_y, max_x, max_y
    else:
        # 正常情况下不应出现
        raise ImageNotSupported(f'Empty bbox {(min_x, min_y, max_x, max_y)}')


def get_bbox_reversed(image, threshold=255):
    """
    获取图像内容的外接边界框（反向阈值）。
    pillow getbbox() 的 opencv 实现。

    Args:
        image (np.ndarray): 图像数组。
        threshold (int): 颜色阈值。
            color < threshold 视为内容，color >= threshold 视为背景。

    Returns:
        tuple[int, int, int, int]: 边界框区域 (x1, y1, x2, y2)。

    Raises:
        ImageNotSupported: 获取边界框失败时抛出。
    """
    channel = image_channel(image)
    # 转换为灰度图
    if channel == 3:
        # RGB
        mask = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        cv2.threshold(mask, 0, threshold, cv2.THRESH_BINARY, dst=mask)
    elif channel == 0:
        # 灰度图
        mask = cv2.threshold(image, 0, threshold, cv2.THRESH_BINARY)
    elif channel == 4:
        # RGBA
        mask = cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
        cv2.threshold(mask, 0, threshold, cv2.THRESH_BINARY, dst=mask)
    else:
        raise ImageNotSupported(f'shape={image.shape}')

    # 查找边界框
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_y, min_x = mask.shape
    max_x = 0
    max_y = 0
    # 全黑图像
    if not contours:
        raise ImageNotSupported(f'Cannot get bbox from a pure black image')
    for contour in contours:
        # x, y, w, h
        x1, y1, x2, y2 = cv2.boundingRect(contour)
        x2 += x1
        y2 += y1
        if x1 < min_x:
            min_x = x1
        if y1 < min_y:
            min_y = y1
        if x2 > max_x:
            max_x = x2
        if y2 > max_y:
            max_y = y2
    if min_x < max_x and min_y < max_y:
        return min_x, min_y, max_x, max_y
    else:
        # 正常情况下不应出现
        raise ImageNotSupported(f'Empty bbox {(min_x, min_y, max_x, max_y)}')


def color_similarity(color1, color2):
    """计算两个颜色之间的差异度。

    Args:
        color1 (tuple): 颜色1 (r, g, b)。
        color2 (tuple): 颜色2 (r, g, b)。

    Returns:
        int: 颜色差异度。
    """
    # print(color1, color2)
    # diff = np.array(color1).astype(int) - np.array(color2).astype(int)
    # diff = np.max(np.maximum(diff, 0)) - np.min(np.minimum(diff, 0))
    diff_r = color1[0] - color2[0]
    diff_g = color1[1] - color2[1]
    diff_b = color1[2] - color2[2]

    max_positive = 0
    max_negative = 0
    if diff_r > max_positive:
        max_positive = diff_r
    elif diff_r < max_negative:
        max_negative = diff_r
    if diff_g > max_positive:
        max_positive = diff_g
    elif diff_g < max_negative:
        max_negative = diff_g
    if diff_b > max_positive:
        max_positive = diff_b
    elif diff_b < max_negative:
        max_negative = diff_b

    diff = max_positive - max_negative
    return diff


def color_similar(color1, color2, threshold=10):
    """
    判断两个颜色是否相似，当容差小于等于阈值时视为相似。
    容差 = Max(正差值_rgb) + Max(-负差值_rgb)
    与 Photoshop 中的容差计算方式相同。

    Args:
        color1 (tuple): 颜色1 (r, g, b)。
        color2 (tuple): 颜色2 (r, g, b)。
        threshold (int): 容差阈值，默认为 10。

    Returns:
        bool: 两颜色相似返回 True。
    """
    # print(color1, color2)
    # diff = np.array(color1).astype(int) - np.array(color2).astype(int)
    # diff = np.max(np.maximum(diff, 0)) - np.min(np.minimum(diff, 0))
    diff_r = color1[0] - color2[0]
    diff_g = color1[1] - color2[1]
    diff_b = color1[2] - color2[2]

    max_positive = 0
    max_negative = 0
    if diff_r > max_positive:
        max_positive = diff_r
    elif diff_r < max_negative:
        max_negative = diff_r
    if diff_g > max_positive:
        max_positive = diff_g
    elif diff_g < max_negative:
        max_negative = diff_g
    if diff_b > max_positive:
        max_positive = diff_b
    elif diff_b < max_negative:
        max_negative = diff_b

    diff = max_positive - max_negative
    return diff <= threshold


def color_similar_1d(image, color, threshold=10):
    """判断一维图像数组中的颜色是否与指定颜色相似。

    Args:
        image (np.ndarray): 一维数组。
        color: 目标颜色 (r, g, b)。
        threshold (int): 容差阈值，默认为 10。

    Returns:
        np.ndarray: 布尔数组。
    """
    diff = image.astype(int) - color
    diff = np.max(np.maximum(diff, 0), axis=1) - np.min(np.minimum(diff, 0), axis=1)
    return diff <= threshold


def color_similarity_2d(image, color):
    """计算二维图像中每个像素与指定颜色的差异度。

    Args:
        image: 二维图像数组。
        color: 目标颜色 (r, g, b)。

    Returns:
        np.ndarray: 差异度数组，uint8 类型。
    """
    # r, g, b = cv2.split(cv2.subtract(image, (*color, 0)))
    # positive = cv2.max(cv2.max(r, g), b)
    # r, g, b = cv2.split(cv2.subtract((*color, 0), image))
    # negative = cv2.max(cv2.max(r, g), b)
    # return cv2.subtract(255, cv2.add(positive, negative))
    if isinstance(color, tuple) and len(color) == 3:
        color = (*color, 0)
    diff = cv2.subtract(image, color)
    r, g, b = cv2.split(diff)
    cv2.max(r, g, dst=r)
    cv2.max(r, b, dst=r)
    positive = r
    cv2.subtract(color, image, dst=diff)
    r, g, b = cv2.split(diff)
    cv2.max(r, g, dst=r)
    cv2.max(r, b, dst=r)
    negative = r
    cv2.add(positive, negative, dst=positive)
    cv2.subtract(255, positive, dst=positive)
    return positive


def image_color_count(image, color, threshold=221, count=50):
    """判断图像中与指定颜色相似的像素数量是否超过阈值。

    Args:
        image (np.ndarray): 图像数组。
        color (tuple): RGB 颜色。
        threshold (int): 相似度阈值，255 表示完全相同，值越低越宽松。
        count (int): 像素计数阈值。

    Returns:
        bool: 相似像素数超过 count 返回 True。
    """
    mask = color_similarity_2d(image, color=color)
    cv2.inRange(mask, threshold, 255, dst=mask)
    sum_ = cv2.countNonZero(mask)
    return sum_ > count


def extract_letters(image, letter=(255, 255, 255), threshold=128):
    """将字母颜色设为黑色，背景颜色设为白色。

    Args:
        image (np.ndarray): 图像数组，形状 (height, width, channel)。
        letter (tuple): 字母 RGB 颜色。
        threshold (int): 颜色差异阈值。

    Returns:
        np.ndarray: 灰度图，形状 (height, width)。
    """
    # r, g, b = cv2.split(cv2.subtract(image, (*letter, 0)))
    # positive = cv2.max(cv2.max(r, g), b)
    # r, g, b = cv2.split(cv2.subtract((*letter, 0), image))
    # negative = cv2.max(cv2.max(r, g), b)
    # return cv2.multiply(cv2.add(positive, negative), 255.0 / threshold)
    diff = cv2.subtract(image, letter)
    r, g, b = cv2.split(diff)
    cv2.max(r, g, dst=r)
    cv2.max(r, b, dst=r)
    positive = r
    cv2.subtract(letter, image, dst=diff)
    r, g, b = cv2.split(diff)
    cv2.max(r, g, dst=r)
    cv2.max(r, b, dst=r)
    negative = r
    cv2.add(positive, negative, dst=positive)
    if threshold != 255:
        cv2.convertScaleAbs(positive, alpha=255.0 / threshold, dst=positive)
    return positive


def extract_white_letters(image, threshold=128):
    """将字母颜色设为黑色，背景颜色设为白色。
    此函数会抑制彩色像素（非灰度像素）。

    Args:
        image (np.ndarray): 图像数组，形状 (height, width, channel)。
        threshold (int): 颜色差异阈值。

    Returns:
        np.ndarray: 灰度图，形状 (height, width)。
    """
    # minimum = cv2.min(cv2.min(r, g), b)
    # maximum = cv2.max(cv2.max(r, g), b)
    # return cv2.multiply(cv2.add(maximum, cv2.subtract(maximum, minimum)), 255.0 / threshold)
    r, g, b = cv2.split(cv2.subtract((255, 255, 255), image))
    maximum = cv2.max(r, g)
    cv2.min(r, g, dst=r)
    cv2.max(maximum, b, dst=maximum)
    cv2.min(r, b, dst=r)
    # minimum = r

    cv2.convertScaleAbs(maximum, alpha=0.5, dst=maximum)
    cv2.convertScaleAbs(r, alpha=0.5, dst=r)
    cv2.subtract(maximum, r, dst=r)
    cv2.add(maximum, r, dst=maximum)
    if threshold != 255:
        cv2.convertScaleAbs(maximum, alpha=255.0 / threshold, dst=maximum)
    return maximum


def crop_to_text(image, threshold=120, padding=2):
    """裁剪图像宽高以紧密贴合文本内容。

    专为 OCR 预处理后的灰度图设计（extract_letters 的输出），
    其中文本像素值较低，背景像素值为 255。
    查找包含文本的最左、最右、最上、最下的行/列，
    然后裁剪图像到该范围并保留小的安全边距。

    Args:
        image (np.ndarray): 灰度图，形状 (height, width)。
            像素值范围 0~255，较低值表示文本。
        threshold (int): 像素值 < threshold 视为文本。
            默认 120，可安全捕获抗锯齿边缘。
        padding (int): 每边保留的额外像素作为安全边距。
            默认 2。如果文本被裁剪可增大此值。

    Returns:
        np.ndarray: 裁剪后的图像。
            如果未检测到文本，返回原图。
    """
    # 创建文本像素掩码（值 < threshold）
    # 检测灰度图（2D）或多通道图（3D）中的文本
    mask = np.any(image < threshold, axis=2) if image.ndim == 3 else image < threshold

    # 查找包含文本的行和列
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)

    if not rows.any() or not cols.any():
        return image

    # 边界索引
    row_idx = np.where(rows)[0]
    col_idx = np.where(cols)[0]

    h, w = image.shape[:2]
    top = max(row_idx[0] - padding, 0)
    bottom = min(row_idx[-1] + padding + 1, h)
    left = max(col_idx[0] - padding, 0)
    right = min(col_idx[-1] + padding + 1, w)

    return image[top:bottom, left:right]


def color_mapping(image, max_multiply=2):
    """将颜色映射到 0-255 范围。
    最小颜色映射到 0，最大颜色映射到 255，颜色倍增最大为 2。

    Args:
        image (np.ndarray): 图像数组。
        max_multiply (int, float): 最大倍增系数。

    Returns:
        np.ndarray: 映射后的图像数组。
    """
    image = image.astype(float)
    low, high = np.min(image), np.max(image)
    multiply = min(255 / (high - low), max_multiply)
    add = (255 - multiply * (low + high)) / 2
    # image = cv2.add(cv2.multiply(image, multiply), add)
    cv2.multiply(image, multiply, dst=image)
    cv2.add(image, add, dst=image)
    image[image > 255] = 255
    image[image < 0] = 0
    return image.astype(np.uint8)


def image_left_strip(image, threshold, length):
    """裁剪图像左侧部分。
    例如在 `DAILY:200/200` 中去除 `DAILY:` 只保留 `200/200`。

    Args:
        image (np.ndarray): 图像数组，形状 (height, width)。
        threshold (int): 亮度阈值 (0-255)。
            亮度低于此值的第一列视为左边缘。
        length (int): 从左边缘开始裁剪的长度。

    Returns:
        np.ndarray: 裁剪后的图像。
    """
    brightness = np.mean(image, axis=0)
    match = np.where(brightness < threshold)[0]

    if len(match):
        left = match[0] + length
        total = image.shape[1]
        if left < total:
            image = image[:, left:]
    return image


def red_overlay_transparency(color1, color2, red=247):
    """计算红色叠加层的透明度。

    Args:
        color1: 原始颜色。
        color2: 变化后的颜色。
        red (int): 红色值 (0-255)。默认 247。

    Returns:
        float: 透明度 (0-1)。
    """
    return (color2[0] - color1[0]) / (red - color1[0])


def color_bar_percentage(image, area, prev_color, reverse=False, starter=0, threshold=30):
    """计算颜色进度条的百分比。

    Args:
        image (np.ndarray): 图像数组。
        area (tuple): 进度条区域 (x1, y1, x2, y2)。
        prev_color (tuple): 进度条颜色 (r, g, b)。
        reverse (bool): 进度条是否从右向左。默认 False。
        starter (int): 起始列索引。默认 0。
        threshold (int): 颜色相似度阈值。默认 30。

    Returns:
        float: 百分比 (0 到 1)。
    """
    image = crop(image, area, copy=False)
    image = image[:, ::-1, :] if reverse else image
    length = image.shape[1]
    prev_index = starter

    for _ in range(1280):
        bar = color_similarity_2d(image, color=prev_color)
        index = np.where(np.any(bar > 255 - threshold, axis=0))[0]
        if not index.size:
            return prev_index / length
        else:
            index = index[-1]
        if index <= prev_index:
            return index / length
        prev_index = index

        prev_row = bar[:, prev_index] > 255 - threshold
        if not prev_row.size:
            return prev_index / length
        # 向前回溯 5 像素获取平均颜色
        left = max(prev_index - 5, 0)
        mask = np.where(bar[:, left:prev_index + 1] > 255 - threshold)
        prev_color = np.mean(image[:, left:prev_index + 1][mask], axis=0)

    return 0.
