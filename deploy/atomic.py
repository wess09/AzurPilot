import os
import random
import string
import time
from typing import Iterable, Union

IS_WINDOWS = os.name == 'nt'
# 其他进程正在读写时的最大重试次数，仅在 Windows 上生效
WINDOWS_MAX_ATTEMPT = 5
# 重试之间的基础等待时间（秒）
WINDOWS_RETRY_DELAY = 0.05


def random_id():
    """生成 6 位随机 ID，用于临时文件命名。

    Returns:
        str: 随机 ID，如 "sTD2kF"。
    """
    # 6 位随机字符（62^6 种组合）已足够避免冲突
    return ''.join(random.sample(string.ascii_letters + string.digits, 6))


def is_tmp_file(file: str) -> bool:
    """判断文件名是否为临时文件（由 atomic 模块生成）。

    先检查后缀以减少正则调用，再验证随机 ID 格式。

    Returns:
        bool: 是否为临时文件。
    """
    if not file.endswith('.tmp'):
        return False
    dot = file[-11:-10]
    if not dot:
        return False
    rid = file[-10:-4]
    return rid.isalnum()


def to_tmp_file(file: str) -> str:
    """将文件名或目录名转换为临时文件名。

    Args:
        file: 原始文件名，如 "filename"。

    Returns:
        str: 临时文件名，如 "filename.sTD2kF.tmp"。
    """
    suffix = random_id()
    return f'{file}.{suffix}.tmp'


def to_nontmp_file(file: str) -> str:
    """将临时文件名还原为原始文件名。

    Args:
        file: 临时文件名，如 "filename.sTD2kF.tmp"。

    Returns:
        str: 原始文件名，如 "filename"。
    """
    if is_tmp_file(file):
        return file[:-11]
    else:
        return file


def windows_attempt_delay(attempt: int) -> float:
    """Windows 上文件被占用时的指数退避等待时间。

    Args:
        attempt: 当前尝试次数，从 0 开始。

    Returns:
        float: 需要等待的秒数。
    """
    return 2 ** attempt * WINDOWS_RETRY_DELAY


def replace_tmp(tmp: str, file: str):
    """将临时文件替换为目标文件。

    在 Windows 上，如果其他进程正在读取文件，会进行指数退避重试。

    Raises:
        PermissionError: （仅 Windows）其他进程仍在读取文件且所有重试均失败。
        FileNotFoundError: 临时文件被意外删除。
    """
    if IS_WINDOWS:
        # Windows 上其他进程正在读取时会抛出 PermissionError
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                # 原子操作
                os.replace(tmp, file)
                return
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
            except FileNotFoundError:
                # 临时文件被意外删除
                raise
            except Exception as e:
                last_error = e
                break
    else:
        # Linux 和 Mac 允许在读取时替换
        try:
            # 原子操作
            os.replace(tmp, file)
            return
        except FileNotFoundError:
            raise
        except Exception as e:
            last_error = e

    # 失败时清理临时文件
    try:
        os.unlink(tmp)
    except FileNotFoundError:
        # 临时文件已被删除
        pass
    except:
        pass
    if last_error is not None:
        raise last_error from None


def atomic_replace(replace_from: str, replace_to: str):
    """原子替换文件或目录。

    Windows 上如果其他进程正在读取，会进行指数退避重试。

    Raises:
        PermissionError: （仅 Windows）其他进程仍在读取且所有重试均失败。
        FileNotFoundError: 源文件不存在。
    """
    if IS_WINDOWS:
        # Windows 上其他进程正在读取时会抛出 PermissionError
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                # 原子操作
                os.replace(replace_from, replace_to)
                return
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
            except FileNotFoundError:
                raise
            except Exception as e:
                last_error = e
                break
        if last_error is not None:
            raise last_error from None
    else:
        # Linux 和 Mac 直接替换
        os.replace(replace_from, replace_to)


def file_write(file: str, data: Union[str, bytes]):
    """将数据写入文件，自动创建父目录。

    根据数据类型自动选择写入模式（文本或二进制）。
    写入后强制刷新到磁盘。
    """
    if isinstance(data, str):
        mode = 'w'
        encoding = 'utf-8'
        newline = ''
    elif isinstance(data, bytes):
        mode = 'wb'
        encoding = None
        newline = None
        # 像 Pathlib 一样创建 memoryview
        data = memoryview(data)
    else:
        typename = str(type(data))
        if typename == "<class 'numpy.ndarray'>":
            mode = 'wb'
            encoding = None
            newline = None
        else:
            mode = 'w'
            encoding = 'utf-8'
            newline = ''

    try:
        with open(file, mode=mode, encoding=encoding, newline=newline) as f:
            f.write(data)
            # 确保数据刷新到磁盘
            f.flush()
            os.fsync(f.fileno())
    except FileNotFoundError:
        # 父目录不存在，先创建
        directory = os.path.dirname(file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(file, mode=mode, encoding=encoding, newline=newline) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())


def file_write_stream(file: str, data_generator):
    """流式写入文件，仅在生成器产出数据时才创建文件。

    根据第一个数据块的类型自动选择写入模式。

    Args:
        file: 目标文件路径。
        data_generator: 可迭代对象，产出 str 或 bytes 数据块。
    """
    data_iter = iter(data_generator)

    # 尝试获取第一个数据块
    try:
        first_chunk = next(data_iter)
    except StopIteration:
        # 生成器为空，不创建文件
        return

    # 根据第一个数据块确定写入模式
    if isinstance(first_chunk, str):
        mode = 'w'
        encoding = 'utf-8'
        newline = ''
    elif isinstance(first_chunk, bytes):
        mode = 'wb'
        encoding = None
        newline = None
    else:
        mode = 'w'
        encoding = 'utf-8'
        newline = ''

    try:
        with open(file, mode=mode, encoding=encoding, newline=newline) as f:
            f.write(first_chunk)
            for chunk in data_iter:
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
    except FileNotFoundError:
        directory = os.path.dirname(file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(file, mode=mode, encoding=encoding, newline=newline) as f:
            f.write(first_chunk)
            for chunk in data_iter:
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())


def atomic_write(
        file: str,
        data: Union[str, bytes],
):
    """原子写入文件，先写临时文件再替换。

    os.replace() 在所有操作系统上都是原子操作，
    因此先写入临时文件再执行替换，可安全处理其他进程同时读取的情况。

    Args:
        file: 目标文件路径。
        data: 要写入的数据（str 或 bytes）。
    """
    temp = to_tmp_file(file)
    file_write(temp, data)
    replace_tmp(temp, file)


def atomic_write_stream(
        file: str,
        data_generator,
):
    """原子流式写入文件，支持流式数据。

    先写入临时文件再替换，可安全处理其他进程同时读取的情况。

    Args:
        file: 目标文件路径。
        data_generator: 可迭代对象，产出 str 或 bytes 数据块。
    """
    temp = to_tmp_file(file)
    file_write_stream(temp, data_generator)
    replace_tmp(temp, file)


def file_read_text(
        file: str,
        encoding: str = 'utf-8',
        errors: str = 'strict'
) -> str:
    """读取文本文件。

    Args:
        file: 文件路径。
        encoding: 文件编码，默认 utf-8。
        errors: 错误处理模式，如 'strict'、'ignore'、'replace'。

    Returns:
        str: 文件内容，文件不存在时返回空字符串。
    """
    try:
        with open(file, mode='r', encoding=encoding, errors=errors) as f:
            return f.read()
    except FileNotFoundError:
        return ''


def file_read_text_stream(
        file: str,
        encoding: str = 'utf-8',
        errors: str = 'strict',
        chunk_size: int = 8192
) -> Iterable[str]:
    """流式读取文本文件。

    Args:
        file: 文件路径。
        encoding: 文件编码，默认 utf-8。
        errors: 错误处理模式，如 'strict'、'ignore'、'replace'。
        chunk_size: 每次读取的字符数，默认 8192。

    Yields:
        str: 文件内容块。
    """
    try:
        with open(file, mode='r', encoding=encoding, errors=errors) as f:
            while 1:
                chunk = f.read(chunk_size)
                if not chunk:
                    return
                yield chunk
    except FileNotFoundError:
        return


def file_read_bytes(file: str) -> bytes:
    """读取二进制文件。

    Args:
        file: 文件路径。

    Returns:
        bytes: 文件内容，文件不存在时返回空 bytes。
    """
    try:
        # 读取整个文件时不使用 Python 缓冲以加速读取
        # https://github.com/python/cpython/pull/122111
        with open(file, mode='rb', buffering=0) as f:
            return f.read()
    except FileNotFoundError:
        return b''


def file_read_bytes_stream(file: str, chunk_size: int = 8192) -> Iterable[bytes]:
    """流式读取二进制文件。

    Args:
        file: 文件路径。
        chunk_size: 每次读取的字节数，默认 8192。

    Yields:
        bytes: 文件内容块。
    """
    try:
        with open(file, mode='rb') as f:
            while 1:
                chunk = f.read(chunk_size)
                if not chunk:
                    return
                yield chunk
    except FileNotFoundError:
        return


def atomic_read_text(
        file: str,
        encoding: str = 'utf-8',
        errors: str = 'strict'
) -> str:
    """原子读取文本文件。

    Windows 上如果其他进程正在替换文件，会进行指数退避重试。

    Args:
        file: 文件路径。
        encoding: 文件编码，默认 utf-8。
        errors: 错误处理模式，如 'strict'、'ignore'、'replace'。

    Returns:
        str: 文件内容。
    """
    if IS_WINDOWS:
        # Windows 上其他进程正在替换时会抛出 PermissionError
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                return file_read_text(file, encoding=encoding, errors=errors)
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
        if last_error is not None:
            raise last_error from None
    else:
        # Linux 和 Mac 允许在替换时读取
        return file_read_text(file, encoding=encoding, errors=errors)


def atomic_read_text_stream(
        file: str,
        encoding: str = 'utf-8',
        errors: str = 'strict',
        chunk_size: int = 8192
) -> Iterable[str]:
    """原子流式读取文本文件。

    Args:
        file: 文件路径。
        encoding: 文件编码，默认 utf-8。
        errors: 错误处理模式。
        chunk_size: 每次读取的字符数，默认 8192。

    Yields:
        str: 文件内容块。
    """
    if IS_WINDOWS:
        # Windows 上其他进程正在替换时会抛出 PermissionError
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                yield from file_read_text_stream(file, encoding=encoding, errors=errors, chunk_size=chunk_size)
                return
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
        if last_error is not None:
            raise last_error from None
    else:
        # Linux 和 Mac 允许在替换时读取
        yield from file_read_text_stream(file, encoding=encoding, errors=errors, chunk_size=chunk_size)
        return


def atomic_read_bytes(file: str) -> bytes:
    """原子读取二进制文件。

    Windows 上如果其他进程正在替换文件，会进行指数退避重试。
    """
    if IS_WINDOWS:
        # Windows 上其他进程正在替换时会抛出 PermissionError
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                return file_read_bytes(file)
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
        if last_error is not None:
            raise last_error from None
    else:
        # Linux 和 Mac 允许在替换时读取
        return file_read_bytes(file)


def atomic_read_bytes_stream(file: str, chunk_size: int = 8192) -> Iterable[bytes]:
    """原子流式读取二进制文件。

    Args:
        file: 文件路径。
        chunk_size: 每次读取的字节数，默认 8192。

    Yields:
        bytes: 文件内容块。
    """
    if IS_WINDOWS:
        # Windows 上其他进程正在替换时会抛出 PermissionError
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                yield from file_read_bytes_stream(file, chunk_size=chunk_size)
                return
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
        if last_error is not None:
            raise last_error from None
    else:
        # Linux 和 Mac 允许在替换时读取
        yield from file_read_bytes_stream(file, chunk_size=chunk_size)
        return


def file_remove(file: str):
    """非原子删除文件。"""
    try:
        os.unlink(file)
    except FileNotFoundError:
        # 文件不存在，无需删除
        pass


def atomic_remove(file: str):
    """原子删除文件。

    Args:
        file: 文件路径。
    """
    if IS_WINDOWS:
        # Windows 上其他进程正在替换时会抛出 PermissionError
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                return file_remove(file)
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
        if last_error is not None:
            raise last_error from None
    else:
        # Linux 和 Mac 允许在其他进程读取时删除
        # 目录条目会被移除，但文件占用的存储空间要等到原文件不再使用时才释放
        return file_remove(file)


def folder_rmtree(folder, may_symlinks=True):
    """递归删除目录及其内容。

    Args:
        folder: 目录路径。
        may_symlinks: 是否可能是符号链接，默认 True。
            如果已知不是符号链接可设为 False。

    Returns:
        bool: 是否成功。
    """
    try:
        # 如果是符号链接，直接删除链接本身
        if may_symlinks and os.path.islink(folder):
            file_remove(folder)
            return True
        # 遍历目录
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    folder_rmtree(entry.path, may_symlinks=False)
                else:
                    # 文件或符号链接，只删除链接本身
                    try:
                        file_remove(entry.path)
                    except PermissionError:
                        # 其他进程正在读写
                        pass

    except FileNotFoundError:
        # 目录不存在，无需清理
        return True
    except NotADirectoryError:
        file_remove(folder)
        return True

    # 删除空目录，如果目录非空会抛出 OSError
    try:
        os.rmdir(folder)
        return True
    except FileNotFoundError:
        return True
    except NotADirectoryError:
        file_remove(folder)
        return True
    except OSError:
        return False


def atomic_rmtree(folder: str):
    """原子删除目录。

    先将目录重命名为临时目录再删除，如果删除过程中断，
    下次启动时可由 atomic_failure_cleanup 清理残留。
    """
    temp = to_tmp_file(folder)
    try:
        atomic_replace(folder, temp)
    except FileNotFoundError:
        # 目录不存在，无需删除
        return
    folder_rmtree(temp)


def atomic_failure_cleanup(folder: str, recursive: bool = False):
    """清理指定路径下的残留临时文件。

    正常情况下不应有残留临时文件，除非写入过程中断。
    此方法应仅在启动时调用，以避免删除其他进程正在写入的临时文件。

    Args:
        folder: 要清理的目录路径。
        recursive: 是否递归清理子目录。
    """
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if is_tmp_file(entry.name):
                    try:
                        # 删除临时文件或目录
                        if entry.is_dir(follow_symlinks=False):
                            folder_rmtree(entry.path, may_symlinks=False)
                        else:
                            file_remove(entry.path)
                    except PermissionError:
                        # 其他进程正在读写
                        pass
                    except:
                        pass
                else:
                    if recursive:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                atomic_failure_cleanup(entry.path, recursive=True)
                        except:
                            pass

    except FileNotFoundError:
        # 目录不存在，无需清理
        pass
    except NotADirectoryError:
        file_remove(folder)
    except:
        # 忽略所有失败，临时文件残留不影响功能
        pass
