"""Source-resolution display pipeline, independent of frozen model preprocessing."""

import io
import numpy as np
from PIL import Image




def pixel_data(path):
    import pydicom
    ds = pydicom.dcmread(path)
    pixels = ds.pixel_array.astype(np.float32)
    if pixels.ndim != 2 or not np.isfinite(pixels).all():
        raise ValueError('Viewer requires a finite, single-frame grayscale image.')
    pixels = pixels * float(getattr(ds, 'RescaleSlope', 1)) + float(getattr(ds, 'RescaleIntercept', 0))
    if not np.isfinite(pixels).all():
        raise ValueError('DICOM rescale produced invalid pixel values.')
    return ds, pixels



def display_metadata(path):
    ds, pixels = pixel_data(path)
    low, high = np.percentile(pixels, [1, 99])
    def first(value):
        return float(value[0] if hasattr(value, '__len__') and not isinstance(value, str) else value)
    width = first(ds.WindowWidth) if hasattr(ds, 'WindowWidth') else max(1, float(high - low))
    center = first(ds.WindowCenter) if hasattr(ds, 'WindowCenter') else float((high + low) / 2)
    if not np.isfinite(width) or not np.isfinite(center) or width < 1:
        width, center = max(1, float(high-low)), float((high+low)/2)
    return dict(width=int(ds.Columns), height=int(ds.Rows), windowWidth=width, windowCenter=center)




def render(path, width=None, center=None, cam_path=None, opacity=.45):
    ds, pixels = pixel_data(path)
    meta = display_metadata(path) if width is None or center is None else None
    width = width if width is not None else meta['windowWidth']
    center = center if center is not None else meta['windowCenter']

    # DICOM linear window, including width=1 threshold behavior.

    gray = (pixels > center - .5).astype(np.float32) if width <= 1 else np.clip((pixels-(center-.5))/(width-1)+.5, 0, 1)
    if str(getattr(ds, 'PhotometricInterpretation', '')) == 'MONOCHROME1':
        gray = 1-gray
    rgb = np.repeat(gray[..., None], 3, axis=2)
    if cam_path:
        cam = np.load(cam_path, allow_pickle=False)
        if cam.shape != (224, 224) or not np.isfinite(cam).all():
            raise ValueError('Invalid class attention map.')
        cam = np.asarray(Image.fromarray(cam).resize((pixels.shape[1], pixels.shape[0]), Image.Resampling.BILINEAR))
        heat = np.stack([cam, np.maximum(0, 1-np.abs(cam-.5)*2), 1-cam], axis=-1)
        alpha = np.clip(cam, 0, 1)[..., None] * opacity
        rgb = rgb*(1-alpha)+heat*alpha
    result = io.BytesIO()
    Image.fromarray(np.uint8(np.clip(rgb, 0, 1)*255)).save(result, format='PNG')
    return result.getvalue()
