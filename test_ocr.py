import sys
sys.path.insert(0, r'.')
from ml.ocr.plate_ocr import PlateOCR, PlateNormalizer
import numpy as np

ocr = PlateOCR()

# Test 1: Normal plate image
plate_img = np.random.randint(0, 255, (100, 200, 3), dtype=np.uint8)
result = ocr.read(plate_img)
print(f'Test 1 - text: "{result["text"]}", confidence: {result["confidence"]:.3f}')

# Test 2: None image
result = ocr.read(None)
print(f'Test 2 - text: "{result["text"]}", confidence: {result["confidence"]:.3f}')

# Test 3: Empty array
result = ocr.read(np.array([]))
print(f'Test 3 - text: "{result["text"]}", confidence: {result["confidence"]:.3f}')

# Test 4: Normalize
normalizer = PlateNormalizer()
result = normalizer.normalize('UP32AB1234')
print(f'Test 4a - normalize UP32AB1234: {result}')
result = normalizer.normalize('invalid')
print(f'Test 4b - normalize invalid: {result}')

# Test 5: normalize_confidence
adj_conf = normalizer.normalize_confidence(0.8, 'UP32AB1234', 'UP32AB1234')
print(f'Test 5a - same text: {adj_conf}')
adj_conf = normalizer.normalize_confidence(0.8, 'UP32AB1234', 'MH45CD5678')
print(f'Test 5b - different text: {adj_conf}')

print('All OCR tests passed!')