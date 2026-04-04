import os
import cv2
import numpy as np


class SoilDetector:
    def __init__(self):
        # Load two sample images for different soil types
        template1_path = os.path.join(os.path.dirname(__file__), 'templates', 'soil1.JPG')
        template2_path = os.path.join(os.path.dirname(__file__), 'templates', 'soil2.JPG')

        self.template1 = cv2.imread(template1_path)
        self.template2 = cv2.imread(template2_path)

        # Calculate colors for both soil types separately
        self.template1_color = np.mean(self.template1, axis=(0, 1))
        self.template2_color = np.mean(self.template2, axis=(0, 1))

        self.color_threshold = 15
        self.min_contour_area = 5000  # Minimum area in pixels to filter out small false positives

    def detect(self, screen):
        # Thresholding/Masking - find pixels similar to EITHER soil1 OR soil2
        diff1 = np.abs(screen - self.template1_color)
        mask1 = (np.mean(diff1, axis=2) < self.color_threshold).astype(np.uint8) * 255

        diff2 = np.abs(screen - self.template2_color)
        mask2 = (np.mean(diff2, axis=2) < self.color_threshold).astype(np.uint8) * 255

        # Combine both masks
        current_mask = cv2.bitwise_or(mask1, mask2)

        # Close gaps - this will connect the horizontal lines into a solid region
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        current_mask = cv2.morphologyEx(current_mask, cv2.MORPH_CLOSE, kernel)

        # Find contours from the combined mask
        contours, _ = cv2.findContours(current_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None, current_mask, None, None

        # Filter contours by minimum area (removes small false positives like snow patches)
        valid_contours = [c for c in contours if cv2.contourArea(c) > self.min_contour_area]

        if not valid_contours:
            return None, current_mask, None, None

        # Get the largest contour (the soil plot)
        largest = max(valid_contours, key=cv2.contourArea)

        # Find the minimum area rotated rectangle that encloses the contour
        # This "fills in" missing corners and gives us the true rectangle shape
        min_rect = cv2.minAreaRect(largest)
        center = (int(min_rect[0][0]), int(min_rect[0][1]))  # Center of the rectangle

        # Get the 4 corners of the rectangle for drawing
        box_points = cv2.boxPoints(min_rect)
        box_points = np.int32(box_points)

        # Shape matching - approximate the polygon for visualization
        epsilon = 0.02 * cv2.arcLength(largest, True)
        approx = cv2.approxPolyDP(largest, epsilon, True)

        return approx, current_mask, center, box_points

    def getSoilCenter(self, screen):
        """Returns the center point (x, y) of the detected soil plot."""
        _, _, center, _ = self.detect(screen)
        return center

    def getSoilBounds(self, screen):
        """
        Returns the bounding box of the detected soil plot.
        Returns (min_x, min_y, max_x, max_y, center_x, center_y)

        Uses the bounding rect of the largest valid contour, NOT the full mask.
        Using the full mask caused stray false-positive pixels at screen edges
        to expand min_x/max_x to the full screen width.
        """
        _, mask, center, _ = self.detect(screen)

        if mask is None or center is None:
            return None

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in contours if cv2.contourArea(c) > self.min_contour_area]

        if not valid:
            return None

        largest = max(valid, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(largest)

        return (x, y, x + w, y + h, center[0], center[1])
