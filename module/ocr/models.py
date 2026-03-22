from module.base.decorator import cached_property


class OcrModel:
    @cached_property
    def azur_lane(self):
        from module.ocr.al_ocr import AlOcr
        return AlOcr(name='en')

    @cached_property
    def azur_lane_jp(self):
        from module.ocr.al_ocr import AlOcr
        return AlOcr(name='en')

    @cached_property
    def cnocr(self):
        from module.ocr.al_ocr import AlOcr
        return AlOcr(name='zhcn')

    @cached_property
    def jp(self):
        from module.ocr.al_ocr import AlOcr
        return AlOcr(name='en')

    @cached_property
    def tw(self):
        from module.ocr.al_ocr import AlOcr
        return AlOcr(name='zhcn')

OCR_MODEL = OcrModel()

