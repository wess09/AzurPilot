"""养成计算、舰船资料与文件导入接口。"""
import base64
import binascii
import csv
import io
import json
import zipfile
from pathlib import Path
from xml.etree.ElementTree import ParseError

from pydantic import ValidationError

from module.api.protocol import ApiError, MindShip
from module.runtime import dock_data
from module.runtime.fleet_database import FleetDatabase
from module.runtime.mind_calculator import RARITY_NAMES, catalog


def input_ship(ship):
    """规范化用户输入的舰船字段并校验类型；底账内部序号不作为导入身份。"""
    if isinstance(ship, dict):
        ship = {key: value for key, value in ship.items() if key != 'id'}
    return MindShip.model_validate(ship).model_dump()


def decode(content):
    """解码导入文件的内容并检查数据格式。"""
    try:
        return base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error):
        raise ApiError('INVALID_PARAMS', '文件内容不是有效的 Base64') from None


def table_ships(rows):
    """按表头读取舰船数据，不依据位置猜测列含义。"""
    aliases = {'name': ('name', '船名', '舰船', '名称'), 'level': ('level', '等级'),
               'rarity': ('rarity', '稀有度'), 'base_rarity': ('base_rarity', '基础稀有度'),
               'review': ('review', '需核对'), 'source': ('source', '来源'),
               'extra_exp': ('extra_exp', '额外经验', '零散经验')}
    columns = None
    output = []
    for index, row in enumerate(rows):
        if index > 5020:
            raise ValueError('最多导入 5000 艘舰船')
        if columns is None:
            header = [str(cell or '').strip() for cell in row]
            columns = {key: next((header.index(name) for name in names if name in header), -1)
                       for key, names in aliases.items()}
            if columns['name'] < 0 or columns['level'] < 0:
                columns = None
                if index >= 19:
                    break
                continue
            continue
        def value(key, default=''):
            """读取导入单元格并转为可用的字符串。"""
            column = columns[key]
            return row[column] if 0 <= column < len(row) and row[column] is not None else default
        name = str(value('name')).strip()
        if len(name) > 1 and name.startswith("'") and name[1:2] in '=+-@\t\r':
            name = name[1:]
        if not name:
            continue
        raw_level = value('level', 0)
        if raw_level == '':
            raw_level = 0
        if isinstance(raw_level, bool) or str(raw_level).strip() not in {str(x) for x in range(126)}:
            raise ValueError(f'第 {index + 1} 行等级必须为 0 至 125 的整数')
        rarity = str(value('rarity')).strip()
        rarity = {cn: key for key, cn in RARITY_NAMES.items()}.get(rarity, rarity.upper())
        base_rarity = str(value('base_rarity')).strip()
        base_rarity = {cn: key for key, cn in RARITY_NAMES.items()}.get(base_rarity, base_rarity.upper())
        def boolean(key):
            """将导入的标记字段转换为布尔值。"""
            raw = str(value(key)).strip().casefold()
            if raw not in ('', '0', '1', 'true', 'false', '是', '否'):
                raise ValueError(f'第 {index + 1} 行 {key} 字段无效')
            return raw in ('1', 'true', '是')
        raw_exp = value('extra_exp', '')
        extra_exp = None
        if raw_exp != '' and raw_exp is not None:
            if isinstance(raw_exp, bool) or not str(raw_exp).strip().isdigit():
                raise ValueError(f'第 {index + 1} 行额外经验必须为非负整数或留空')
            extra_exp = int(raw_exp)
        output.append(input_ship(dict(extra_exp=extra_exp, name=name, level=int(raw_level), rarity=rarity,
                                      base_rarity=base_rarity, review=boolean('review'),
                                      source=str(value('source'))[:200])))
    if columns is None:
        raise ValueError('缺少“船名”和“等级”表头')
    return output


def import_ships(filename, content):
    """从上传的文件中解析舰船列表。"""
    raw = decode(content)
    suffix = Path(filename).suffix.casefold()
    try:
        if suffix == '.json':
            data = json.loads(raw.decode('utf-8-sig'))
            items = data.get('ships') if isinstance(data, dict) else data
            if not isinstance(items, list) or len(items) > 5000:
                raise ValueError('JSON 必须含 ships 数组，最多 5000 艘')
            return [input_ship(ship) for ship in items]
        if suffix == '.csv':
            return table_ships(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
        if suffix == '.xlsx':
            from openpyxl import load_workbook
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(item.file_size for item in archive.infolist()) > 32 * 1024 * 1024:
                    raise ValueError('Excel 解压后超过 32 MiB 限制')
            book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True, keep_links=False)
            try:
                sheet = book['舰船明细'] if '舰船明细' in book.sheetnames else book.active
                rows = list(sheet.iter_rows(max_row=5021, max_col=20, values_only=True))
                return table_ships(rows)
            finally:
                book.close()
        raise ValueError('请选择 JSON、CSV 或 XLSX 文件')
    except (ValueError, TypeError, KeyError, ValidationError, zipfile.BadZipFile, OSError, ParseError) as exc:
        raise ApiError('INVALID_PARAMS', f'导入失败：{exc}') from None


class MindCalculatorService:
    def __init__(self, configs):
        """绑定配置服务并初始化心智计算器接口。"""
        self.configs = configs


    def plan(self, instance, expected_revision, ship_ids, target_level):
        """Project selected card IDs against one confirmed revision without writing facts."""
        from module.runtime.fleet_cultivation import project
        data = FleetDatabase(self.configs.path(instance)).load()
        snapshot = dock_data.read_snapshot(data)
        if snapshot['revision'] != expected_revision:
            raise ApiError('CONFLICT', '舰船数据已更新，请重新载入后计算')
        return dict(instance=instance, revision=snapshot['revision'],
                    **project(snapshot['ships'], ship_ids, target_level))


    def catalog(self, instance):
        """返回用于计算与人工核对的舰船资料。"""
        self.configs.path(instance)
        data = catalog()
        return dict(updated_at=data['updated_at'], ships=list(data['ships'].values()))


    def import_file(self, instance, filename, content):
        """解析用户上传文件并返回可检查的舰船记录。"""
        self.configs.path(instance)
        return {'ships': import_ships(filename, content)}

    def recognize(self, instance, filename, content):
        """识别上传截图中的舰船卡片和等级。"""
        self.configs.path(instance)
        from PIL import Image, UnidentifiedImageError
        from module.runtime.mind_calculator import recognize
        try:
            raw = decode(content)
            if len(raw) > 5_500_000:
                raise ValueError('图片超过 5.5 MB 限制，请压缩后重试')
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('PNG', 'JPEG', 'WEBP'):
                    raise ValueError('图片格式不支持，请上传 PNG、JPEG 或 WebP')
                ships = recognize(image, Path(filename.replace('\\', '/')).name)
        except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise ApiError('INVALID_PARAMS', f'截图识别失败：{exc}') from None
        except RuntimeError as exc:
            raise ApiError('OCR_UNAVAILABLE', f'OCR 引擎无法完成识别，请检查模型和 OCR 配置：{str(exc)[:200]}') from None
        return {'ships': ships}
