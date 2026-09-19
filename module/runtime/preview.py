"""被动截图通道：游戏线程只投递图像，后台编码，父进程分发最新帧。"""
import base64
import io
import queue
import threading
from datetime import datetime


class PreviewHub:
    """每实例只保留一帧，订阅者通过通知取最新值，不累积视频队列。"""

    def __init__(self):
        self.frames = {}
        self.listeners = set()
        self.lock = threading.Lock()

    def publish(self, instance, frame):
        with self.lock:
            self.frames[instance] = frame
            listeners = tuple(self.listeners)
        for listener in listeners:
            listener(instance)

    def get(self, instance):
        with self.lock:
            return self.frames.get(instance, {'instance': instance, 'image': None, 'capturedAt': None})

    def discard(self, instance):
        with self.lock:
            self.frames.pop(instance, None)

    def subscribe(self, listener):
        with self.lock:
            self.listeners.add(listener)

    def unsubscribe(self, listener):
        with self.lock:
            self.listeners.discard(listener)


hub = PreviewHub()
_images = None


def initialize(instance, output, task_sink, run_id=None):
    """在运行子进程中安装输出通道，独立脚本无需初始化。"""
    from module.runtime.worker_events import initialize as initialize_events

    global _images
    initialize_events(task_sink, run_id)
    _images = queue.Queue(maxsize=1)

    def encode():
        from PIL import Image
        while True:
            image, timestamp = _images.get()
            try:
                buffer = io.BytesIO()
                # 各后端在统一截图入口返回 RGB 图像。
                Image.fromarray(image).save(buffer, format='JPEG', quality=85)
                frame = {'instance': instance, 'capturedAt': timestamp, 'runId': run_id,
                         'image': 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode()}
                try:
                    output.put_nowait(frame)
                except queue.Full:
                    try:
                        output.get_nowait()
                    except queue.Empty:
                        pass
                    output.put_nowait(frame)
            except (OSError, EOFError, BrokenPipeError):
                return
            except (ValueError, queue.Full):
                # 预览丢帧不能中断实际任务或造成无界积压。
                continue

    threading.Thread(target=encode, daemon=True, name='preview-encoder').start()


def publish(image):
    """接收统一截图入口的结果，复制后交给编码线程，避免后续画图污染。"""
    if _images is None:
        return
    frame = (image.copy(), datetime.now().isoformat())
    try:
        _images.put_nowait(frame)
    except queue.Full:
        try:
            _images.get_nowait()
        except queue.Empty:
            pass
        try:
            _images.put_nowait(frame)
        except queue.Full:
            pass


def set_task(command):
    """沿用可靠的日志队列传递任务边界，避免从日志文字推测状态。"""
    from module.runtime.worker_events import set_task as publish_task

    publish_task(command)
