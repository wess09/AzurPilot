from module.ocr.ocr import *
from module.base.button import *
from module.ui.ui import *


class WarehouseOCR:
    def __init__(self, *args, **kwargs):
        self.warehouse_grid = ButtonGrid(
            origin=(301, 150),
            delta=(142, 167),
            button_shape=(104, 110),
            grid_shape=(6, 2),
            name="WAREHOUSE_GRID"
        )
        self.number_area_relative = (45, 90, 99, 110)
    def ocr_item_quantity(self, screenshot, template):
        for _, _, button in self.warehouse_grid.generate():
            cell_image = crop(screenshot, button.area)
            if template.match(cell_image, similarity=0.85):
                number_area = self._get_number_area(button)
                ocr_button = Button(
                    area=number_area,
                    color=(),
                    button=number_area,
                    name="ITEM_NUMBER"
                )
                ocr_instance = Digit(ocr_button,letter = (255, 255, 255), threshold = 200,
                alphabet = '0123456789')
                return ocr_instance.ocr(screenshot)
        return 0

    def _get_number_area(self, button):
        x1 = button.area[0] + self.number_area_relative[0]
        y1 = button.area[1] + self.number_area_relative[1]
        x2 = button.area[0] + self.number_area_relative[2]
        y2 = button.area[1] + self.number_area_relative[3]
        return (x1, y1, x2, y2)