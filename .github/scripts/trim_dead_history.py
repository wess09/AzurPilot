"""移除历史中已经不存在于当前工作树的路径，供 gitcode 镜像瘦身使用。

镜像仓库的容量配额是 1 GiB，而历史里累积了大量后来被替换或删除的大文件（旧版 OCR
模型、构建产物、安装包等）。这些路径在当前工作树中已经不存在，却仍然从分支顶端
可达，所以普通 `git gc` 回收不掉。

本脚本把「历史中存在、当前树中不存在」的路径整理出来，交给 git-filter-repo 从历史中
移除。只删这些路径，提交正文、作者、时间与提交顺序都保持不变（提交 ID 会变）。

该变换对同一份输入是确定的：同一段历史跑多少次结果都一样，因此各次同步产出的 SHA
稳定，客户端可以正常 pull；新增提交只是在结果之上继续延伸。

用法（在仓库根目录）：

    python .github/scripts/trim_dead_history.py
"""
import os
import re
import subprocess
import sys
import tempfile


def git(args, check=True):
    return subprocess.run(
        ['git', '-c', 'core.quotePath=false', *args],
        check=check, capture_output=True, text=True,
        encoding='utf-8', errors='replace',
    )


def dead_paths():
    """历史中出现过、但当前树中已不存在的路径。"""
    history = set()
    for line in git(['rev-list', '--objects', 'HEAD']).stdout.splitlines():
        path = line.partition(' ')[2]
        if path:
            history.add(path)
    current = set(git(['ls-tree', '-r', '--name-only', 'HEAD']).stdout.splitlines())
    # git-filter-repo 的路径条目按「该路径及其整个子树」处理，所以必须排除同时是活动
    # 目录前缀的条目（例如历史上存在过名为 bin 的文件，而当前 bin/ 是活动目录）。
    return sorted(p for p in history - current if not any(c.startswith(p + '/') for c in current))


def main():
    paths = dead_paths()
    if not paths:
        print('没有历史死重，跳过清理')
        return 0
    print(f'历史死重路径 {len(paths)} 条，开始清理')

    handle, list_file = tempfile.mkstemp(suffix='.txt', text=True)
    with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as f:
        for path in paths:
            f.write('regex:^' + re.escape(path) + '$\n')
    try:
        subprocess.run(
            ['git', 'filter-repo', '--force',
             '--preserve-commit-hashes', '--prune-empty=never',
             '--invert-paths', '--paths-from-file', list_file],
            check=True,
        )
    finally:
        os.unlink(list_file)

    # filter-repo 自带的清理不会回收仍被其他引用挂住的对象，这里强制回收一次，
    # 否则旧对象会留在 pack 里，瘦身效果出不来。
    git(['reflog', 'expire', '--expire=now', '--all'], check=False)
    git(['gc', '--prune=now'], check=False)
    print('清理完成')
    return 0


if __name__ == '__main__':
    sys.exit(main())
