"""日志到达通知：父进程写入 renderable 后唤醒 WebSocket 订阅者。"""
import threading


class LogHub:
    """不缓存日志正文，只通知实例名；正文仍由 RuntimeService.logs 按游标读取。"""

    def __init__(self):
        self.listeners = set()
        self.lock = threading.Lock()

    def publish(self, instance):
        with self.lock:
            listeners = tuple(self.listeners)
        for listener in listeners:
            listener(instance)

    def subscribe(self, listener):
        with self.lock:
            self.listeners.add(listener)

    def unsubscribe(self, listener):
        with self.lock:
            self.listeners.discard(listener)


hub = LogHub()
