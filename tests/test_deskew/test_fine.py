import cv2
import numpy as np
from PIL import Image

def detect_fine_skew(image: Image.Image) -> float:
    """Detect skew angle in degrees (-15 to 15) using OpenCV Hough lines on text."""
    # Convert PIL Image to OpenCV grayscale
    img_cv = np.array(image.convert("L"))
    
    # Resize for speed and noise reduction if very large
    h, w = img_cv.shape
    scale = 1.0
    if max(h, w) > 1500:
        scale = 1500 / max(h, w)
        img_cv = cv2.resize(img_cv, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    # Invert and binarize
    thresh = cv2.threshold(img_cv, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]

    # Dilate horizontally to merge letters into text lines
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))
    dilated = cv2.dilate(thresh, kernel, iterations=1)

    # Detect line segments using Probabilistic Hough Transform
    lines = cv2.HoughLinesP(dilated, 1, np.pi / 180, threshold=100, minLineLength=60, maxLineGap=15)
    
    if lines is None:
        return 0.0

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line.flatten()[:4]
        dx = float(x2 - x1)
        dy = float(y2 - y1)
        if dx == 0:
            continue
        angle = np.degrees(np.arctan2(dy, dx))
        # Keep only nearly horizontal lines (between -20 and 20 degrees)
        if -20.0 <= angle <= 20.0:
            angles.append(angle)

    if not angles:
        return 0.0

    # Median angle is resilient to outliers/drawings
    median_angle = float(np.median(angles))
    return median_angle

# Test on 0.png with forced 5.0 deg rotation
base = Image.open("tests/test_deskew/input/0.png")
for test_angle in [3.0, 5.0, -7.5, 0.0]:
    rotated = base.rotate(test_angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    detected = detect_fine_skew(rotated)
    print(f"Forced: {test_angle:+5.1f}° -> Detected: {detected:+5.2f}° (error: {abs(detected - test_angle):.2f}°)")
