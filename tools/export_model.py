# -*- coding: utf-8 -*-
"""一键导出 YOLO 模型 → NCNN（.param/.bin）。

用法（需先 pip install ultralytics）：
    python tools/export_model.py [yolo26n|yolov8n|yolo11n] [imgsz=640]

产物写入 dist/models/<name>_ncnn.param / <name>_ncnn.bin，
可通过手机端「模型管理」页导入，或 adb push 到 files/models/。
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "dist", "models"))


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "yolo26n"
    imgsz = int(sys.argv[2]) if len(sys.argv) > 2 else 640

    from ultralytics import YOLO  # 延迟导入，避免无 ultralytics 时报错过早

    print(f"[1/3] 加载 {name}.pt ...")
    model = YOLO(f"{name}.pt")

    print(f"[2/3] 导出 NCNN (imgsz={imgsz}, fp16) ...")
    export_path = model.export(format="ncnn", imgsz=imgsz, half=True)

    src = export_path if os.path.isdir(export_path) else os.path.dirname(export_path)
    os.makedirs(OUT, exist_ok=True)
    # 产物命名兼容：新版 model.ncnn.param；旧版 model.param
    param_src = os.path.join(src, "model.ncnn.param")
    if not os.path.exists(param_src):
        param_src = os.path.join(src, "model.param")
    bin_src = os.path.join(src, "model.ncnn.bin")
    if not os.path.exists(bin_src):
        bin_src = os.path.join(src, "model.bin")
    param_dst = os.path.join(OUT, f"{name}_ncnn.param")
    bin_dst = os.path.join(OUT, f"{name}_ncnn.bin")
    shutil.copy(param_src, param_dst)
    shutil.copy(bin_src, bin_dst)
    print(f"[3/3] 完成 -> {param_dst} ({os.path.getsize(param_dst) / 1024:.0f} KB)")
    print(f"      -> {bin_dst} ({os.path.getsize(bin_dst) / 1024 / 1024:.1f} MB)")
    print("提示：可选 --name 的模型（yolov8n/yolo11n 更小更稳），或调整 imgsz 如 416。")


if __name__ == "__main__":
    main()
