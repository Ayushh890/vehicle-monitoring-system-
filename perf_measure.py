import sys
sys.path.insert(0, r'.')

import time
import numpy as np

print('=' * 60)
print('PROMPT 25: Performance Optimization - Baseline Measurements')
print('=' * 60)

# 1. Frame processing latency
print('\n[1] Frame Processing Latency')
sys.path.insert(0, r'.')
from app.core.pipeline import AIEventPipeline

pipeline = AIEventPipeline()
frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

latencies = []
for i in range(50):
    start = time.perf_counter()
    result = pipeline.run(frame)
    end = time.perf_counter()
    latencies.append((end - start) * 1000)

avg_latency = sum(latencies) / len(latencies)
min_latency = min(latencies)
max_latency = max(latencies)
fps = 1000 / avg_latency
print(f'  Average: {avg_latency:.3f} ms')
print(f'  Min: {min_latency:.3f} ms')
print(f'  Max: {max_latency:.3f} ms')
print(f'  Frames per second: {fps:.1f} FPS')

# 2. OCR latency
print('\n[2] OCR Latency')
sys.path.insert(0, r'.')
from ml.ocr.plate_ocr import PlateOCR

ocr = PlateOCR()
plate_img = np.random.randint(0, 255, (100, 200, 3), dtype=np.uint8)

ocr_latencies = []
for i in range(20):
    start = time.perf_counter()
    result = ocr.read(plate_img)
    end = time.perf_counter()
    ocr_latencies.append((end - start) * 1000)

avg_ocr = sum(ocr_latencies) / len(ocr_latencies)
print(f'  Average: {avg_ocr:.3f} ms')
print(f'  Text length: {len(result.get("text", ""))}')
print(f'  Confidence: {result.get("confidence", 0):.3f}')

# 3. Memory usage
print('\n[3] Memory Usage')
import tracemalloc
tracemalloc.start()

from app.core.source import LocalWebcamSource
from app.models import CameraConfig

ws = LocalWebcamSource('0')
ws.open()
config = CameraConfig(camera_id=1, rtsp_url='rtsp://example.com:554/stream')

current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
ws.release()
print(f'  Current: {current / 1024:.1f} KB')
print(f'  Peak: {peak / 1024:.1f} KB')

# 4. Summary
print('\n' + '=' * 60)
print('BASELINE MEASUREMENTS SUMMARY')
print('=' * 60)
print('''
1. Frame Processing Latency:
   - Average: {avg_latency:.3f} ms
   - Equivalent FPS: {fps:.1f} FPS
   - This is the source-agnostic pipeline only (no AI model inference)

2. OCR Latency:
   - Average: {avg_ocr:.3f} ms per plate read
   - With tesseract OCR on numpy arrays

3. Memory Usage:
   - Current: {current / 1024:.1f} KB
   - Peak: {peak / 1024:.1f} KB

Note: Actual AI model inference (detection/tracking/OCR models) would add significant latency.
The pipeline itself is very fast - the bottleneck will be the AI models.
'''.format(avg_latency=avg_latency, fps=fps, avg_ocr=avg_ocr, current=current, peak=peak))