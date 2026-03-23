import time
import numpy as np
from module.daemon.daemon_base import DaemonBase
from module.exception import RequestHumanTakeover
from module.logger import logger
from module.ocr.al_ocr import AlOcr

class OcrBenchmark(DaemonBase):
    def run(self):
        logger.hr('OCR Benchmark', level=1)
        ocr = AlOcr(name='en')  # Default to 'en' model for benchmarking, or parameterize it
        logger.info('Initializing OCR model...')
        ocr.init()
        
        # Create a dummy image resembling a standard text box with noise and a simple gradient
        # While RapidOCR handles real text better, this provides a consistent input for timing throughput
        dummy_img = np.random.randint(0, 128, (64, 256, 3), dtype=np.uint8)
        
        logger.info('Starting OCR loop for 10000 times...')
        
        # Warm-up to load CUDA/DML contexts properly and avoid initial lag
        for _ in range(3):
            ocr.ocr(dummy_img)
            
        start_time = time.time()
        for i in range(1, 10001):
            try:
                ocr.ocr(dummy_img)
                if i % 1000 == 0:
                    logger.info(f'OCR Iteration: {i}/10000 completed...')
            except Exception as e:
                logger.error(f'OCR Error on iteration {i}: {e}')
                break
                
        cost = time.time() - start_time
        logger.hr('OCR Benchmark Results', level=1)
        logger.info(f'OCR completed 10000 times. Total time cost: {cost:.3f}s')
        if cost > 0:
            avg_ms = cost * 1000 / 10000
            logger.info(f'Average time per OCR inference: {avg_ms:.3f} ms')
            
        # Give a visual evaluation like the regular benchmark
        if avg_ms < 5.0:
            speed = 'Insane Fast'
        elif avg_ms < 10.0:
            speed = 'Ultra Fast'
        elif avg_ms < 20.0:
            speed = 'Very Fast'
        elif avg_ms < 40.0:
            speed = 'Fast'
        elif avg_ms < 80.0:
            speed = 'Medium'
        elif avg_ms < 150.0:
            speed = 'Slow'
        elif avg_ms < 300.0:
            speed = 'Very Slow'
        else:
            speed = 'Ultra Slow'
            
        logger.info(f'Performance Rating: {speed}')
        

def run_ocr_benchmark(config):
    try:
        OcrBenchmark(config, task='OcrBenchmark').run()
        return True
    except RequestHumanTakeover:
        logger.critical('错误 请求人类接管')
        return False
