import numpy as np
from scipy import optimize

from module.base.utils import area_pad


class Points:
    def __init__(self, points):
        if points is None or len(points) == 0:
            self._bool = False
            self.points = None
        else:
            self._bool = True
            self.points = np.array(points)
            if len(self.points.shape) == 1:
                self.points = np.array([self.points])
            self.x, self.y = self.points.T

    def __str__(self):
        return str(self.points)

    __repr__ = __str__

    def __iter__(self):
        return iter(self.points)

    def __getitem__(self, item):
        return self.points[item]

    def __len__(self):
        if self:
            return len(self.points)
        else:
            return 0

    def __bool__(self):
        return self._bool

    def link(self, point, is_horizontal=False):
        if is_horizontal:
            lines = [[y, np.pi / 2] for y in self.y]
            return Lines(lines, is_horizontal=True)
        else:
            x, y = point
            theta = -np.arctan((self.x - x) / (self.y - y))
            rho = self.x * np.cos(theta) + self.y * np.sin(theta)
            lines = np.array([rho, theta]).T
            return Lines(lines, is_horizontal=False)

    def mean(self):
        if not self:
            return None

        return np.round(np.mean(self.points, axis=0)).astype(int)

    def group(self, threshold=3):
        if not self:
            return np.array([])
        groups = []
        points = self.points
        if len(points) == 1:
            return np.array([points[0]])

        while len(points):
            p0, p1 = points[0], points[1:]
            distance = np.sum(np.abs(p1 - p0), axis=1)
            new = Points(np.append(p1[distance <= threshold], [p0], axis=0)).mean().tolist()
            groups.append(new)
            points = p1[distance > threshold]

        return np.array(groups)


class Lines:
    MID_Y = 360

    def __init__(self, lines, is_horizontal):
        if lines is None or len(lines) == 0:
            self._bool = False
            self.lines = None
        else:
            self._bool = True
            self.lines = np.array(lines)
            if len(self.lines.shape) == 1:
                self.lines = np.array([self.lines])
            self.rho, self.theta = self.lines.T
        self.is_horizontal = is_horizontal

    def __str__(self):
        return str(self.lines)

    __repr__ = __str__

    def __iter__(self):
        return iter(self.lines)

    def __getitem__(self, item):
        return Lines(self.lines[item], is_horizontal=self.is_horizontal)

    def __len__(self):
        if self:
            return len(self.lines)
        else:
            return 0

    def __bool__(self):
        return self._bool

    @property
    def sin(self):
        return np.sin(self.theta)

    @property
    def cos(self):
        return np.cos(self.theta)

    @property
    def mean(self):
        if not self:
            return None
        if self.is_horizontal:
            return np.mean(self.lines, axis=0)
        else:
            x = np.mean(self.mid)
            theta = np.mean(self.theta)
            rho = x * np.cos(theta) + self.MID_Y * np.sin(theta)
            return np.array((rho, theta))

    @property
    def mid(self):
        if not self:
            return np.array([])
        if self.is_horizontal:
            return self.rho
        else:
            return (self.rho - self.MID_Y * self.sin) / self.cos

    def get_x(self, y):
        return (self.rho - y * self.sin) / self.cos

    def get_y(self, x):
        return (self.rho - x * self.cos) / self.sin

    def add(self, other):
        if not other:
            return self
        if not self:
            return other
        lines = np.append(self.lines, other.lines, axis=0)
        return Lines(lines, is_horizontal=self.is_horizontal)

    def move(self, x, y):
        if not self:
            return self
        if self.is_horizontal:
            self.lines[:, 0] += y
        else:
            self.lines[:, 0] += x * self.cos + y * self.sin
        return Lines(self.lines, is_horizontal=self.is_horizontal)

    def sort(self):
        if not self:
            return self
        lines = self.lines[np.argsort(self.mid)]
        return Lines(lines, is_horizontal=self.is_horizontal)

    def group(self, threshold=3):
        if not self:
            return self
        lines = self.sort()
        prev = 0
        regrouped = []
        group = []
        for mid, line in zip(lines.mid, lines.lines):
            line = line.tolist()
            if mid - prev > threshold:
                if len(regrouped) == 0:
                    if len(group) != 0:
                        regrouped = [group]
                else:
                    regrouped += [group]
                group = [line]
            else:
                group.append(line)
            prev = mid
        regrouped += [group]
        regrouped = np.vstack([Lines(r, is_horizontal=self.is_horizontal).mean for r in regrouped])
        return Lines(regrouped, is_horizontal=self.is_horizontal)

    def distance_to_point(self, point):
        x, y = point
        return self.rho - x * self.cos - y * self.sin

    @staticmethod
    def cross_two_lines(lines1, lines2):
        for rho1, sin1, cos1 in zip(lines1.rho, lines1.sin, lines1.cos):
            for rho2, sin2, cos2 in zip(lines2.rho, lines2.sin, lines2.cos):
                a = np.array([[cos1, sin1], [cos2, sin2]])
                b = np.array([rho1, rho2])
                yield np.linalg.solve(a, b)

    def cross(self, other):
        points = np.vstack(list(self.cross_two_lines(self, other)))
        points = Points(points)
        return points

    def delete(self, other, threshold=3):
        if not self:
            return self

        other_mid = other.mid
        lines = []
        for mid, line in zip(self.mid, self.lines):
            if np.any(np.abs(other_mid - mid) < threshold):
                continue
            lines.append(line)

        return Lines(lines, is_horizontal=self.is_horizontal)


def area2corner(area):
    """将区域坐标转换为四角点坐标。

    Args:
        area: (x1, y1, x2, y2)。

    Returns:
        np.ndarray: [左上, 右上, 左下, 右下]。
    """
    return np.array([[area[0], area[1]], [area[2], area[1]], [area[0], area[3]], [area[2], area[3]]])


def corner2area(corner):
    """将四角点坐标转换为区域坐标。

    Args:
        corner: [左上, 右上, 左下, 右下]。

    Returns:
        np.ndarray: (x1, y1, x2, y2)。
    """
    x, y = np.array(corner).T
    return np.rint([np.min(x), np.min(y), np.max(x), np.max(y)]).astype(int)


def corner2inner(corner):
    """梯形内接的最大矩形。

    Args:
        corner: ((x0, y0), (x1, y1), (x2, y2), (x3, y3))。

    Returns:
        tuple[int]: (左上x, 左上y, 右下x, 右下y)。
    """
    x0, y0, x1, y1, x2, y2, x3, y3 = np.array(corner).flatten()
    area = tuple(np.rint((max(x0, x2), max(y0, y1), min(x1, x3), min(y2, y3))).astype(int))
    return area


def corner2outer(corner):
    """梯形外接的最小矩形。

    Args:
        corner: ((x0, y0), (x1, y1), (x2, y2), (x3, y3))。

    Returns:
        tuple[int]: (左上x, 左上y, 右下x, 右下y)。
    """
    x0, y0, x1, y1, x2, y2, x3, y3 = np.array(corner).flatten()
    area = tuple(np.rint((min(x0, x2), min(y0, y1), max(x1, x3), max(y2, y3))).astype(int))
    return area


def trapezoid2area(corner, pad=0):
    """将梯形角点转换为区域坐标。

    Args:
        corner: ((x0, y0), (x1, y1), (x2, y2), (x3, y3))。
        pad (int): 填充值。
            正值为内接区域，负值和 0 为外接区域。

    Returns:
        tuple[int]: (左上x, 左上y, 右下x, 右下y)。
    """
    if pad > 0:
        return area_pad(corner2inner(corner), pad=pad)
    elif pad < 0:
        return area_pad(corner2outer(corner), pad=pad)
    else:
        return area_pad(corner2area(corner), pad=pad)


def points_to_area_generator(points, shape):
    """将点阵转换为网格区域生成器。

    Args:
        points (np.ndarray): N x 2 数组。
        shape (tuple): (x, y)。

    Yields:
        tuple, np.ndarray: (x, y), [左上, 右上, 左下, 右下]。
    """
    points = points.reshape(*shape[::-1], 2)
    for y in range(shape[1] - 1):
        for x in range(shape[0] - 1):
            area = np.array([points[y, x], points[y, x + 1], points[y + 1, x], points[y + 1, x + 1]])
            yield ((x, y), area)


def get_map_inner(points):
    """计算点集的中心点。

    Args:
        points (np.ndarray): N x 2 数组。

    Returns:
        np.ndarray: 中心坐标 (x, y)。
    """
    points = np.array(points)
    if len(points.shape) == 1:
        points = np.array([points])

    return np.mean(points, axis=0)


def separate_edges(edges, inner):
    """将边缘分为上下（或左右）两组。

    Args:
        edges: 包含浮点数或整数的可迭代对象。
        inner (float, int): 用于分离边缘的内部参考点。

    Returns:
        float, float: 下边缘和上边缘。未找到时返回 None。
    """
    if len(edges) == 0:
        return None, None
    elif len(edges) == 1:
        edge = edges[0]
        return (None, edge) if edge > inner else (edge, None)
    else:
        lower = [edge for edge in edges if edge < inner]
        upper = [edge for edge in edges if edge > inner]
        lower = lower[0] if len(lower) else None
        upper = upper[-1] if len(upper) else None
        return lower, upper


def perspective_transform(points, data):
    """执行透视变换。

    Args:
        points: 二维数组，形状 (n, 2)。
        data: 透视变换数据，形状 (3, 3) 的二维数组，
            参见 https://web.archive.org/web/20150222120106/xenia.media.mit.edu/~cwren/interpolator/

    Returns:
        np.ndarray: 二维数组，形状 (n, 2)。
    """
    points = np.pad(np.array(points), ((0, 0), (0, 1)), mode='constant', constant_values=1)
    matrix = data.dot(points.T)
    x, y = matrix[0] / matrix[2], matrix[1] / matrix[2]
    points = np.array([x, y]).T
    return points


def fit_points(points, mod, encourage=1):
    """在一组具有公差点中找到最接近的拟合点。
    会忽略距离较远的点。

    Args:
        points: 图像上的点，二维数组，形状 (n, 2)。
        mod: 点的公差，(x, y)。
        encourage (int, float): 拟合一组点的接近程度，单位为像素。
            越小越接近局部最小值，越大越接近全局最小值。

    Returns:
        np.ndarray: 拟合点 (x, y)。
    """
    encourage = np.square(encourage)
    mod = np.array(mod)
    points = np.array(points) % mod
    points = np.append(points - mod, points, axis=0)

    def cal_distance(point):
        distance = np.linalg.norm(points - point, axis=1)
        return np.sum(1 / (1 + np.exp(encourage / distance) / distance))

    # 快速局部最小化器
    # result = optimize.minimize(cal_distance, np.mean(points, axis=0), method='SLSQP')
    # return result['x'] % mod

    # 暴力全局最小化器
    area = np.append(-mod - 10, mod + 10)
    result = optimize.brute(cal_distance, ((area[0], area[2]), (area[1], area[3])))
    return result % mod
