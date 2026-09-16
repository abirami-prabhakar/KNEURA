import torch
import torch.nn.functional as F
import numpy as np

TARGET_LAYER_PATH = "backbone.features.8.0"
HEATMAP_SIZE = (224, 224)


class KneeAIGradCAM:

    def __init__(self, model):

        self.model = model
        self.model.eval()

        self.activations = None
        self.gradients = None

        self.target_layer = (
            self.model.backbone.features[8][0]
        )

        self.forward_handle = (
            self.target_layer.register_forward_hook(
                self._forward_hook
            )
        )

        self.backward_handle = (
            self.target_layer.register_full_backward_hook(
                self._backward_hook
            )
        )

    def _forward_hook(
        self,
        module,
        inputs,
        output
    ):

        self.activations = output

    def _backward_hook(
        self,
        module,
        grad_input,
        grad_output
    ):

        self.gradients = grad_output[0]

    def generate(
        self,
        x,
        class_index
    ):

        if x.ndim != 4:
            raise ValueError(
                "Expected input shape [1,5,224,224]"
            )

        if x.shape[0] != 1:
            raise ValueError(
                "Grad-CAM expects batch size 1"
            )

        if tuple(x.shape[1:]) != (
            5,
            224,
            224
        ):

            raise ValueError(
                "Expected input shape [1,5,224,224]"
            )

        self.model.zero_grad(
            set_to_none=True
        )

        logits = self.model(x)

        if logits.ndim != 2:
            raise RuntimeError(
                "Unexpected model output shape"
            )

        if not (
            0 <= class_index < logits.shape[1]
        ):

            raise IndexError(
                "Invalid class_index"
            )

        selected_logit = (
            logits[:, class_index]
        )

        probability = torch.sigmoid(
            selected_logit
        ).detach().cpu().item()

        selected_logit.backward()

        if self.activations is None:
            raise RuntimeError(
                "Activations were not captured"
            )

        if self.gradients is None:
            raise RuntimeError(
                "Gradients were not captured"
            )

        weights = self.gradients.mean(
            dim=(2, 3),
            keepdim=True
        )

        cam = (
            weights * self.activations
        ).sum(
            dim=1,
            keepdim=True
        )

        cam = F.relu(cam)

        cam = F.interpolate(
            cam,
            size=HEATMAP_SIZE,
            mode="bilinear",
            align_corners=False
        )

        cam = cam[0, 0]

        cam_min = cam.min()
        cam_max = cam.max()

        if (
            cam_max - cam_min
        ).item() > 0:

            cam = (
                (cam - cam_min)
                / (cam_max - cam_min)
            )

        else:

            cam = torch.zeros_like(cam)

        heatmap = (
            cam.detach()
            .cpu()
            .numpy()
            .astype(np.float32)
        )

        return heatmap, float(probability)

    def close(self):

        self.forward_handle.remove()
        self.backward_handle.remove()


def generate_gradcam(
    model,
    input_tensor,
    class_index
):

    cam = KneeAIGradCAM(model)

    try:

        return cam.generate(
            input_tensor,
            class_index
        )

    finally:

        cam.close()
