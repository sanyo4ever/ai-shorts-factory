from __future__ import annotations

import sys
from pathlib import Path

PATCHED_PREPROCESSING = """import sys
from face_detection import FaceAlignment, LandmarksType
from os import listdir, path
import subprocess
import numpy as np
import cv2
import pickle
import os
import json
from mmpose.apis import inference_topdown, init_model
from mmpose.structures import merge_data_samples
import torch
from tqdm import tqdm

# initialize the mmpose model
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
config_file = "./musetalk/utils/dwpose/rtmpose-l_8xb32-270e_coco-ubody-wholebody-384x288.py"
checkpoint_file = "./models/dwpose/dw-ll_ucoco_384.pth"
model = init_model(config_file, checkpoint_file, device=device)

# initialize the face detection model
device = "cuda" if torch.cuda.is_available() else "cpu"
fa = FaceAlignment(LandmarksType._2D, flip_input=False, device=device)

# marker if the bbox is not sufficient
coord_placeholder = (0.0, 0.0, 0.0, 0.0)


def _safe_average(values):
    if not values:
        return 0
    return int(sum(values) / len(values))


def _landmark_bbox_and_ranges(face_land_mark, upperbondrange=0):
    half_face_coord = face_land_mark[29].copy()
    range_minus = int((face_land_mark[30] - face_land_mark[29])[1])
    range_plus = int((face_land_mark[29] - face_land_mark[28])[1])
    if upperbondrange != 0:
        half_face_coord[1] = upperbondrange + half_face_coord[1]
    half_face_dist = np.max(face_land_mark[:, 1]) - half_face_coord[1]
    min_upper_bond = 0
    upper_bond = max(min_upper_bond, half_face_coord[1] - half_face_dist)
    landmark_bbox = (
        int(np.min(face_land_mark[:, 0])),
        int(upper_bond),
        int(np.max(face_land_mark[:, 0])),
        int(np.max(face_land_mark[:, 1])),
    )
    return landmark_bbox, range_minus, range_plus


def _is_valid_bbox(bbox):
    x1, y1, x2, y2 = bbox
    return y2 - y1 > 0 and x2 - x1 > 0 and x1 >= 0 and y1 >= 0


def resize_landmark(landmark, w, h, new_w, new_h):
    w_ratio = new_w / w
    h_ratio = new_h / h
    landmark_norm = landmark / [w, h]
    landmark_resized = landmark_norm * [new_w, new_h]
    return landmark_resized


def read_imgs(img_list):
    frames = []
    print("reading images...")
    for img_path in tqdm(img_list):
        frame = cv2.imread(img_path)
        frames.append(frame)
    return frames


def get_bbox_range(img_list, upperbondrange=0):
    frames = read_imgs(img_list)
    batch_size_fa = 1
    batches = [frames[i : i + batch_size_fa] for i in range(0, len(frames), batch_size_fa)]
    coords_list = []
    landmarks = []
    if upperbondrange != 0:
        print("get key_landmark and face bounding boxes with the bbox_shift:", upperbondrange)
    else:
        print("get key_landmark and face bounding boxes with the default value")
    average_range_minus = []
    average_range_plus = []
    for fb in tqdm(batches):
        results = inference_topdown(model, np.asarray(fb)[0])
        results = merge_data_samples(results)
        keypoints = results.pred_instances.keypoints
        face_land_mark = keypoints[0][23:91]
        face_land_mark = face_land_mark.astype(np.int32)

        bbox = fa.get_detections_for_batch(np.asarray(fb))
        f_landmark, range_minus, range_plus = _landmark_bbox_and_ranges(
            face_land_mark,
            upperbondrange=upperbondrange,
        )
        landmark_bbox_valid = _is_valid_bbox(f_landmark)

        for f in bbox:
            if f is None and not landmark_bbox_valid:
                coords_list += [coord_placeholder]
                continue
            if landmark_bbox_valid:
                average_range_minus.append(range_minus)
                average_range_plus.append(range_plus)

    text_range = (
        f"Total frame:「{len(frames)}」 Manually adjust range : "
        f"[ -{_safe_average(average_range_minus)}~{_safe_average(average_range_plus)} ] , "
        f"the current value: {upperbondrange}"
    )
    return text_range


def get_landmark_and_bbox(img_list, upperbondrange=0):
    frames = read_imgs(img_list)
    batch_size_fa = 1
    batches = [frames[i : i + batch_size_fa] for i in range(0, len(frames), batch_size_fa)]
    coords_list = []
    landmarks = []
    if upperbondrange != 0:
        print("get key_landmark and face bounding boxes with the bbox_shift:", upperbondrange)
    else:
        print("get key_landmark and face bounding boxes with the default value")
    average_range_minus = []
    average_range_plus = []
    for fb in tqdm(batches):
        results = inference_topdown(model, np.asarray(fb)[0])
        results = merge_data_samples(results)
        keypoints = results.pred_instances.keypoints
        face_land_mark = keypoints[0][23:91]
        face_land_mark = face_land_mark.astype(np.int32)

        bbox = fa.get_detections_for_batch(np.asarray(fb))
        f_landmark, range_minus, range_plus = _landmark_bbox_and_ranges(
            face_land_mark,
            upperbondrange=upperbondrange,
        )
        landmark_bbox_valid = _is_valid_bbox(f_landmark)
        if landmark_bbox_valid:
            average_range_minus.append(range_minus)
            average_range_plus.append(range_plus)

        for f in bbox:
            if f is None:
                if landmark_bbox_valid:
                    coords_list += [f_landmark]
                else:
                    coords_list += [coord_placeholder]
                continue

            if not landmark_bbox_valid:
                coords_list += [f]
                print("error bbox:", f)
            else:
                coords_list += [f_landmark]

    print("********************************************bbox_shift parameter adjustment**********************************************************")
    print(
        f"Total frame:「{len(frames)}」 Manually adjust range : "
        f"[ -{_safe_average(average_range_minus)}~{_safe_average(average_range_plus)} ] , "
        f"the current value: {upperbondrange}"
    )
    print("*************************************************************************************************************************************")
    return coords_list, frames


if __name__ == "__main__":
    img_list = [
        "./results/lyria/00000.png",
        "./results/lyria/00001.png",
        "./results/lyria/00002.png",
        "./results/lyria/00003.png",
    ]
    crop_coord_path = "./coord_face.pkl"
    coords_list, full_frames = get_landmark_and_bbox(img_list)
    with open(crop_coord_path, "wb") as f:
        pickle.dump(coords_list, f)

    for bbox, frame in zip(coords_list, full_frames):
        if bbox == coord_placeholder:
            continue
        x1, y1, x2, y2 = bbox
        crop_frame = frame[y1:y2, x1:x2]
        print("Cropped shape", crop_frame.shape)

    print(coords_list)
"""


def apply_patch(service_root: Path) -> bool:
    preprocessing_path = service_root / "musetalk" / "utils" / "preprocessing.py"
    if not preprocessing_path.exists():
        raise SystemExit(f"MuseTalk preprocessing file not found: {preprocessing_path}")
    current_text = preprocessing_path.read_text(encoding="utf-8", errors="replace")
    normalized_current = current_text.replace("\r\n", "\n")
    normalized_target = PATCHED_PREPROCESSING.replace("\r\n", "\n").rstrip("\n") + "\n"
    if normalized_current == normalized_target:
        print(f"Already patched: {preprocessing_path}")
        return False
    preprocessing_path.write_text(normalized_target, encoding="utf-8")
    print(f"Patched MuseTalk preprocessing: {preprocessing_path}")
    return True


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("Usage: patch_musetalk_preprocessing.py <MuseTalk service root>")
    service_root = Path(argv[1]).resolve()
    apply_patch(service_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
