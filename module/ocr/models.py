from module.base.decorator import cached_property
from module.ocr.al_ocr import AlOcr


class OcrModel:
    @cached_property
    def azur_lane(self):
        return AlOcr(name='en')

    @cached_property
    def azur_lane_jp(self):
        return AlOcr(name='en')

    @cached_property
    def cnocr(self):
        return AlOcr(name='zhcn')

    @cached_property
    def jp(self):
        return AlOcr(name='en')

    @cached_property
    def tw(self):
        return AlOcr(name='zhcn')

OCR_MODEL = OcrModel()

