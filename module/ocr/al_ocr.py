import os
import numpy as np
import cv2
from PIL import Image

from module.exception import RequestHumanTakeover
from module.logger import logger
from module.config.config import AzurLaneConfig

try:
    from rapidocr import RapidOCR, OCRVersion
except Exception as e:
    logger.critical(f"Failed to load OCR dependencies: {e}")
    logger.critical(
        "无法加载 OCR 依赖，请安装微软 C++ 运行库 https://aka.ms/vs/17/release/vc_redist.x64.exe"
    )
    logger.critical("也有可能是 GPU 不支持加速引起，请尝试关闭 GPU 加速")
    logger.critical("如果上述方法都无法解决，请加群获取支持")
    raise RequestHumanTakeover


config_name = os.environ.get("ALAS_CONFIG_NAME")
config = AzurLaneConfig(config_name)
USE_GPU = config.ocr_device == 'gpu'

class CnModel:
    def __init__(self):
        self.params = {
            "Global.use_det": False,
            "Global.use_cls": False,
            "Det.model_path": None,
            "Cls.model_path": None,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_path": "bin/ocr_models/zh-CN/alocr-zh-cn-v3.dtk.onnx",
            "Rec.rec_keys_path": "bin/ocr_models/zh-CN/cn.txt",
            "EngineConfig.onnxruntime.use_dml": USE_GPU
        }
        self.model = RapidOCR(params=self.params)


class EnModel:
    def __init__(self):
        self.params = {
            "Global.use_det": False,
            "Global.use_cls": False,
            "Det.model_path": None,
            "Cls.model_path": None,
            "Rec.ocr_version": OCRVersion.PPOCRV4,
            "Rec.model_path": "bin/ocr_models/en-US/alocr-en-us-v2.6.nvc.onnx",
            "Rec.rec_keys_path": "bin/ocr_models/en-US/en.txt",
            "EngineConfig.onnxruntime.use_dml": USE_GPU
        }
        self.model = RapidOCR(params=self.params)


class JpModel:
    def __init__(self):
        self.params = {
            "Global.use_det": False,
            "Global.use_cls": False,
            "Det.model_path": None,
            "Cls.model_path": None,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_path": "bin/ocr_models/JP/JP.onnx",
            "Rec.rec_keys_path": "bin/ocr_models/JP/ppocrv5_dict.txt",
            "EngineConfig.onnxruntime.use_dml": USE_GPU
        }
        self.model = RapidOCR(params=self.params)


class TwModel:
    def __init__(self):
        self.params = {
            "Global.use_det": False,
            "Global.use_cls": False,
            "Det.model_path": None,
            "Cls.model_path": None,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_path": "bin/ocr_models/TW/TW.onnx",
            "Rec.rec_keys_path": "bin/ocr_models/TW/ppocrv5_dict.txt",
            "EngineConfig.onnxruntime.use_dml": USE_GPU
        }
        self.model = RapidOCR(params=self.params)


cn_model = CnModel()
en_model = EnModel()
jp_model = JpModel()
tw_model = TwModel()


class AlOcr:
    def __init__(self, **kwargs):
        self.model = None
        self.name = kwargs.get("name", "en")
        self.params = {}
        self._model_loaded = False
        logger.info(
            f"Created AlOcr instance: name='{self.name}', kwargs={kwargs}, PID={os.getpid()}"
        )

    def init(self):
        if self.name in ["cn", "zhcn"]:
            self.model = cn_model.model
        elif self.name == "jp":
            self.model = jp_model.model
        elif self.name == "tw":
            self.model = tw_model.model
        else:
            self.model = en_model.model
        self._model_loaded = True

    def _ensure_loaded(self):
        if not self._model_loaded:
            self.init()

    def _save_debug_image(self, img, result):
        folder = "ocr_debug"
        if not os.path.exists(folder):
            os.makedirs(folder)

        # Get current time for filename uniqueness and sorting
        import time

        now = int(time.time() * 1000)
        # Clean result for filename
        res_clean = str(result).replace("\n", " ").replace("\r", " ").strip()
        # Remove invalid filename characters, keep some safe ones
        res_clean = "".join(
            [c for c in res_clean if c.isalnum() or c in (" ", "_", "-")]
        ).strip()
        if not res_clean:
            res_clean = "empty"

        filename = f"{self.name}_{res_clean}_{now}.png"
        filepath = os.path.join(folder, filename)

        try:
            if isinstance(img, np.ndarray):
                cv2.imwrite(filepath, img)
            elif isinstance(img, Image.Image):
                img.save(filepath)
            elif isinstance(img, str) and os.path.exists(img):
                import shutil

                shutil.copy(img, filepath)

            # Limit count to 100
            files = [
                os.path.join(folder, f)
                for f in os.listdir(folder)
                if os.path.isfile(os.path.join(folder, f))
            ]
            if len(files) > 100:
                files.sort(key=os.path.getmtime)
                # Keep the last 100
                for f in files[:-100]:
                    try:
                        os.remove(f)
                    except:
                        pass
        except Exception as e:
            # We don't want to crash the main process due to debug saving failure
            logger.warning(f"Failed to save OCR debug image: {e}")

    def ocr(self, img_fp):
        logger.info(f"[VERBOSE] AlOcr.ocr: Ensure loaded...")
        self._ensure_loaded()

        try:
            res = self.model(img_fp)
            txt = ""
            if hasattr(res, "txts") and res.txts:
                txt = res.txts[0]

            self._save_debug_image(img_fp, txt)
            return txt
        except Exception as e:
            logger.error(f"AlOcr.ocr exception: {e}")
            raise

    def ocr_for_single_line(self, img_fp):
        return self.ocr(img_fp)

    def ocr_for_single_lines(self, img_list):
        self._ensure_loaded()
        results = []
        for i, img in enumerate(img_list):
            try:
                res = self.model(img)
                txt = ""
                if hasattr(res, "txts") and res.txts:
                    txt = res.txts[0]

                results.append(txt)
                self._save_debug_image(img, txt)
            except Exception as e:
                logger.error(f"AlOcr.ocr_for_single_lines exception on image {i}: {e}")
                raise
        return results

    def set_cand_alphabet(self, cand_alphabet):
        pass

    def atomic_ocr(self, img_fp, cand_alphabet=None):
        res = self.ocr(img_fp)
        if cand_alphabet:
            res = "".join([c for c in res if c in cand_alphabet])
        return res

    def atomic_ocr_for_single_line(self, img_fp, cand_alphabet=None):
        res = self.ocr_for_single_line(img_fp)
        if cand_alphabet:
            res = "".join([c for c in res if c in cand_alphabet])
        return res

    def atomic_ocr_for_single_lines(self, img_list, cand_alphabet=None):
        results = self.ocr_for_single_lines(img_list)
        if cand_alphabet:
            results = [
                "".join([c for c in res if c in cand_alphabet]) for res in results
            ]
        return results
