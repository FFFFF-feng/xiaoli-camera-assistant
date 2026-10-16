"""Label every image explicitly; reference coordinates never become primary-image coordinates."""
from camera_assistant.models import ImageInspection


def image_messages(inspection: ImageInspection) -> list[dict]:
    messages = [{"type": "image_url", "image_url": {"url": inspection.model_image_data_url}}]
    for index, image in enumerate(inspection.reference_images, 2):
        messages.extend([
            {"type": "text", "text": f"参考图 photo{index}（不是主图，坐标不可混用）"},
            {"type": "image_url", "image_url": {"url": image.model_image_data_url}},
        ])
    return messages
