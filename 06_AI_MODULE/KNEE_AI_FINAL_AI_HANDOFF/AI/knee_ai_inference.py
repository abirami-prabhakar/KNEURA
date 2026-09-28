
import os
import json
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import pydicom

from PIL import Image
from torchvision import models


# ============================================================
# CONSTANTS
# ============================================================

ABNORMALITIES = [
    "ACL",
    "MCL",
    "Medial Meniscus",
    "Lateral Meniscus",
    "Medial OA",
    "Lateral OA",
    "PF OA",
    "Effusion",
    "Synovitis",
    "Baker's",
    "Contusion",
    "Fracture"
]

IMAGE_SIZE = 224
SLICE_CONTEXT = 5


# ============================================================
# EXACT KNEE-AI 3.3 MODEL
# ============================================================

class StandaloneFiveSliceEfficientNet(nn.Module):

    def __init__(self, num_classes=12):

        super().__init__()

        self.slice_projection = nn.Conv2d(
            5,
            3,
            kernel_size=1,
            stride=1,
            padding=0,
            bias=True
        )

        self.backbone = models.efficientnet_b0(
            weights=None
        )

        self.backbone.classifier[1] = nn.Linear(
            self.backbone.classifier[1].in_features,
            num_classes
        )

        self.register_buffer(
            "imagenet_mean",
            torch.tensor(
                [0.485, 0.456, 0.406]
            ).view(1, 3, 1, 1)
        )

        self.register_buffer(
            "imagenet_std",
            torch.tensor(
                [0.229, 0.224, 0.225]
            ).view(1, 3, 1, 1)
        )

    def forward(self, x):

        x = self.slice_projection(x)

        x = torch.sigmoid(x)

        x = (
            x - self.imagenet_mean
        ) / self.imagenet_std

        return self.backbone(x)


# ============================================================
# EXACT DICOM PREPROCESSING
# ============================================================

def preprocess_dicom(path):

    ds = pydicom.dcmread(path)

    arr = ds.pixel_array.astype(
        np.float32
    )

    # Exact MONOCHROME1 handling
    if getattr(
        ds,
        "PhotometricInterpretation",
        ""
    ) == "MONOCHROME1":

        arr = arr.max() - arr

    # Exact robust normalization
    lo = np.percentile(
        arr,
        1
    )

    hi = np.percentile(
        arr,
        99
    )

    if hi <= lo:

        arr = np.zeros_like(
            arr,
            dtype=np.float32
        )

    else:

        arr = np.clip(
            arr,
            lo,
            hi
        )

        arr = (
            arr - lo
        ) / (
            hi - lo
        )

    # Exact resize
    image = Image.fromarray(
        (
            arr * 255.0
        ).astype(
            np.uint8
        )
    )

    image = image.resize(
        (
            IMAGE_SIZE,
            IMAGE_SIZE
        ),
        Image.Resampling.BILINEAR
    )

    arr = (
        np.asarray(image)
        .astype(np.float32)
        / 255.0
    )

    return torch.from_numpy(
        arr
    ).float()


# ============================================================
# INSTANCE NUMBER ORDERING
# ============================================================

def load_ordered_series(
    series_path
):

    records = []

    for filename in os.listdir(
        series_path
    ):

        path = os.path.join(
            series_path,
            filename
        )

        if not os.path.isfile(path):
            continue

        try:

            ds = pydicom.dcmread(
                path,
                stop_before_pixels=True
            )

            instance_number = getattr(
                ds,
                "InstanceNumber",
                None
            )

            if instance_number is None:
                continue

            records.append({
                "path": path,
                "InstanceNumber":
                    int(instance_number)
            })

        except Exception:
            continue

    records = sorted(
        records,
        key=lambda x:
            x["InstanceNumber"]
    )

    return records


# ============================================================
# 5-SLICE WINDOW GENERATION
# ============================================================

def create_windows(
    ordered_records
):

    n_slices = len(
        ordered_records
    )

    n_windows = max(
        0,
        n_slices - 4
    )

    windows = []

    for center in range(
        2,
        n_slices - 2
    ):

        window = ordered_records[
            center - 2:
            center + 3
        ]

        if len(window) != 5:
            continue

        windows.append(
            window
        )

    assert len(windows) == n_windows

    return windows


# ============================================================
# WINDOW → MODEL INPUT
# ============================================================

def window_to_tensor(
    window
):

    slices = [
        preprocess_dicom(
            item["path"]
        )
        for item in window
    ]

    stacked = torch.stack(
        slices,
        dim=0
    )

    return stacked.unsqueeze(
        0
    )


# ============================================================
# MODEL LOADING
# ============================================================

def load_model(
    checkpoint_path,
    device="cpu"
):

    model = StandaloneFiveSliceEfficientNet(
        num_classes=12
    )

    checkpoint = torch.load(
        checkpoint_path,
        map_location=device
    )

    if isinstance(
        checkpoint,
        dict
    ) and "state_dict" in checkpoint:

        state_dict = checkpoint[
            "state_dict"
        ]

    else:

        state_dict = checkpoint

    model.load_state_dict(
        state_dict
    )

    model.to(device)
    model.eval()

    return model


# ============================================================
# SERIES ELIGIBILITY
# ============================================================

def select_eligible_series(
    train_series_df,
    study_id
):

    rows = train_series_df[
        train_series_df[
            "StudyInstanceUID"
        ].astype(str)
        == str(study_id)
    ]

    eligible = rows[
        (rows["Fluid_Sensitive"] == 1)
        &
        (rows["Fat_Suppression"] == 1)
    ].copy()

    return eligible


# ============================================================
# COMPLETE STUDY INFERENCE
# ============================================================

@torch.no_grad()
def analyze_study(
    study_id,
    study_root,
    train_series_df,
    checkpoint_path,
    device="cpu"
):

    model = load_model(
        checkpoint_path,
        device=device
    )

    eligible = select_eligible_series(
        train_series_df,
        study_id
    )

    all_predictions = []

    series_count = 0
    window_count = 0

    for _, row in eligible.iterrows():

        series_uid = str(
            row["SeriesInstanceUID"]
        )

        series_path = os.path.join(
            study_root,
            series_uid
        )

        if not os.path.isdir(
            series_path
        ):
            continue

        ordered_records = (
            load_ordered_series(
                series_path
            )
        )

        windows = create_windows(
            ordered_records
        )

        series_count += 1

        for window in windows:

            x = window_to_tensor(
                window
            )

            x = x.to(device)

            logits = model(x)

            probabilities = (
                torch.sigmoid(logits)
                .cpu()
                .numpy()[0]
            )

            all_predictions.append(
                probabilities
            )

            window_count += 1

    if len(all_predictions) == 0:

        raise RuntimeError(
            "No valid 5-slice windows "
            "were available for study."
        )

    all_predictions = np.asarray(
        all_predictions,
        dtype=np.float32
    )

    study_probabilities = (
        all_predictions.mean(
            axis=0
        )
    )

    predictions = {
        label: float(
            probability
        )
        for label, probability
        in zip(
            ABNORMALITIES,
            study_probabilities
        )
    }

    return {
        "study": {
            "study_id":
                str(study_id),
            "series_evaluated":
                series_count,
            "windows_evaluated":
                window_count
        },

        "model": {
            "name":
                "KNEE-AI 3.3",
            "architecture":
                "StandaloneFiveSliceEfficientNet",
            "backbone":
                "EfficientNet-B0",
            "input_size":
                [224, 224],
            "slice_context":
                5,
            "num_abnormalities":
                12
        },

        "aggregation":
            "mean_probability_across_study_windows",

        "probabilities":
            predictions
    }
