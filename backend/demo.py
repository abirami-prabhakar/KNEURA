"""Generate explicitly synthetic DICOM input, never precomputed AI results.

Run python -m backend.demo --output .kneura/demo-study.zip, then upload in UI.
"""
import argparse
import io
from pathlib import Path
import zipfile


def create_demo_package(output):
    import numpy as np
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    study, series = generate_uid(), generate_uid()
    # Exclusive creation protects an existing input package from accidental overwrite.
    with zipfile.ZipFile(output, 'x') as archive:
        for number in range(1, 7):
            meta = FileMetaDataset()
            meta.MediaStorageSOPClassUID = MRImageStorage
            meta.MediaStorageSOPInstanceUID = generate_uid()
            meta.TransferSyntaxUID = ExplicitVRLittleEndian
            ds = FileDataset(None, {}, file_meta=meta, preamble=b'\0' * 128)
            ds.SOPClassUID, ds.SOPInstanceUID = meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID
            ds.StudyInstanceUID, ds.SeriesInstanceUID = study, series
            ds.InstanceNumber, ds.Modality = number, 'MR'
            ds.PatientID, ds.PatientName = 'DEMO-SYNTHETIC', 'DEMO^SYNTHETIC'
            ds.ClinicalTrialProtocolName = 'KNEURA-SYNTHETIC-DEMO'
            ds.StudyDescription, ds.SeriesDescription = 'Synthetic software verification', 'PD FS SYNTHETIC'
            ds.StudyDate = '20260924'
            ds.Rows = ds.Columns = 64
            ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, 'MONOCHROME2'
            ds.BitsAllocated = ds.BitsStored = 16
            ds.HighBit, ds.PixelRepresentation = 15, 0
            ds.PixelData = np.random.default_rng(number).integers(0, 4096, (64, 64), dtype=np.uint16).tobytes()
            buffer = io.BytesIO()
            ds.save_as(buffer, enforce_file_format=True)
            archive.writestr(f'{number}.dcm', buffer.getvalue())
        archive.writestr('series.csv', f'StudyInstanceUID,SeriesInstanceUID,Fluid_Sensitive,Fat_Suppression\n{study},{series},1,1\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='.kneura/demo-study.zip')
    args = parser.parse_args()
    print(create_demo_package(args.output))
    print('SYNTHETIC STUDY: artificial noise, not patient MRI. Upload and run the real model; outputs have no clinical meaning.')
