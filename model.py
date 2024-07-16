import cv2
import time
import numpy as np
import pygame
from ultralytics import YOLO

# Global Variables
zones = []
assigned_ids = {}
entry_times = {}
alarm_triggered = {}
last_seen_times = {}
model = None
class_names = ["mobil", "motor", "pagar"]
alarm_sound = None
max_time_in_zone = None

def init_model(model_path):
    global model
    model = YOLO(model_path)

def set_alarm_sound(sound):
    global alarm_sound
    alarm_sound = sound

def create_zones(frame, results):
    global zones
    if zones:
        return
    for result in results:
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            label = box.cls[0]
            if label == 2:  # "pagar"
                zone_x1 = max(0, x1 - 10)
                zone_y1 = max(0, y1 - 10)
                zone_x2 = min(frame.shape[1], x2 + 10)
                zone_y2 = min(frame.shape[0], y2 + 10)
                zones.append((zone_x1, zone_y1, zone_x2, zone_y2, False))

def draw_zones(frame):
    for zone_x1, zone_y1, zone_x2, zone_y2, occupied in zones:
        color = (0, 0, 255) if occupied else (255, 0, 0)
        cv2.rectangle(frame, (zone_x1, zone_y1), (zone_x2, zone_y2), color, 4)
        cv2.putText(frame, "ZONA PAGAR", (zone_x1, zone_y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

def is_inside_zone(x1, y1, x2, y2, zone):
    zone_x1, zone_y1, zone_x2, zone_y2, _ = zone
    center_x = (x1 + x2) // 2
    center_y = (y1 + y2) // 2
    return center_x >= zone_x1 and center_y >= zone_y1 and center_x <= zone_x2 and center_y <= zone_y2

def euclidean_distance(pt1, pt2):
    return np.sqrt((pt1[0] - pt2[0]) ** 2 + (pt1[1] - pt2[1]) ** 2)

def process_frame(frame):
    global assigned_ids, entry_times, alarm_triggered, last_seen_times
    results = model.track(source=frame, show=False, tracker="bytetrack.yaml")
    create_zones(frame, results)
    draw_zones(frame)

    current_boxes, current_labels = [], []
    for result in results:
        for box in result.boxes:
            confidence = box.conf[0]
            if confidence < 0.5: 
                continue

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            label = int(box.cls[0])
            if label in [0, 1]:  # "mobil" or "motor"
                current_boxes.append((x1, y1, x2, y2))
                current_labels.append(label)

    new_assigned_ids = assign_ids_to_boxes(current_boxes, current_labels)
    triggered_alarms = update_zone_status(new_assigned_ids, current_boxes, current_labels, frame)

    assigned_ids = new_assigned_ids
    return frame, triggered_alarms

def assign_ids_to_boxes(current_boxes, current_labels):
    new_assigned_ids = {}
    for i, (x1, y1, x2, y2) in enumerate(current_boxes):
        label = current_labels[i]
        center_current = ((x1 + x2) // 2, (y1 + y2) // 2)
        min_distance, assigned_id = float('inf'), None

        for prev_center, prev_id in assigned_ids.items():
            distance = euclidean_distance(center_current, prev_center)
            if distance < min_distance:
                min_distance = distance
                assigned_id = prev_id

        if assigned_id is None or min_distance > 50:
            assigned_id = len(assigned_ids) + 1

        new_assigned_ids[center_current] = assigned_id
    return new_assigned_ids

def update_zone_status(new_assigned_ids, current_boxes, current_labels, frame):
    global entry_times, alarm_triggered, last_seen_times
    triggered_alarms = []

    current_ids = list(new_assigned_ids.values())
    for assigned_id in list(entry_times.keys()):
        if assigned_id not in current_ids:
            handle_zone_exit(assigned_id)

    for i, (x1, y1, x2, y2) in enumerate(current_boxes):
        label = current_labels[i]
        assigned_id = list(new_assigned_ids.values())[i]

        inside_zone = False
        for j, zone in enumerate(zones):
            if is_inside_zone(x1, y1, x2, y2, zone):
                inside_zone = True
                zones[j] = (zone[0], zone[1], zone[2], zone[3], True)
                handle_zone_entry(assigned_id, label, triggered_alarms)
                break

        if not inside_zone:
            handle_zone_exit(assigned_id)

        draw_detection_box(frame, x1, y1, x2, y2, label, assigned_id, inside_zone)

    return triggered_alarms

def handle_zone_entry(assigned_id, label, triggered_alarms):
    global entry_times, alarm_triggered, last_seen_times
    if assigned_id not in entry_times:
        entry_times[assigned_id] = time.time()
        alarm_triggered[assigned_id] = False
        last_seen_times[assigned_id] = None  # Initialize last_seen as None

    # No longer checking time_in_zone > 20 here
    # Use max_time_in_zone from app.py configuration instead
    time_in_zone = time.time() - entry_times[assigned_id]
    if max_time_in_zone is not None and time_in_zone > max_time_in_zone and not alarm_triggered[assigned_id]:
        print(f"Triggering alarm for ID {assigned_id}, label {label}, time in zone {time_in_zone}")
        if alarm_sound:
            alarm_sound.play(-1)
        alarm_triggered[assigned_id] = True
        triggered_alarms.append((assigned_id, label, time_in_zone, last_seen_times.get(assigned_id)))

def handle_zone_exit(assigned_id):
    global entry_times, alarm_triggered, last_seen_times
    if assigned_id in entry_times:
        time_in_zone = time.time() - entry_times[assigned_id]
        last_seen_times[assigned_id] = entry_times[assigned_id]  # Update last seen when object leaves zone
        del entry_times[assigned_id]

        if assigned_id in alarm_triggered and alarm_triggered[assigned_id]:
            print(f"Stopping alarm for ID {assigned_id}")
            if alarm_sound:
                alarm_sound.stop()
            alarm_triggered[assigned_id] = False

        for j, zone in enumerate(zones):
            zones[j] = (zone[0], zone[1], zone[2], zone[3], False)

def draw_detection_box(frame, x1, y1, x2, y2, label, assigned_id, inside_zone):
    color = (0, 255, 0) if label == 0 else (0, 0, 255)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
    class_name = class_names[label]
    timer_display = time.time() - entry_times.get(assigned_id, time.time()) if inside_zone else 0
    cv2.putText(frame, f"ID : {assigned_id} [{class_name}] [Waktu: {timer_display:.0f} D]", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 3)

def get_triggered_alarms_data(triggered_alarms):
    data = []
    for alarm in triggered_alarms:
        assigned_id, label, time_in_zone, last_seen = alarm
        tanggal_masuk = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(entry_times[assigned_id]))
        total_waktu = time_in_zone
        data.append({
            'id_inzone': assigned_id,
            'label': class_names[label],
            'tanggal_masuk': tanggal_masuk,
            'total_waktu': total_waktu
        })
    return data

def stop_alarm():
    global alarm_sound, entry_times, alarm_triggered, zones, last_seen_times
    if alarm_sound:
        alarm_sound.stop()
    entry_times.clear()
    alarm_triggered.clear()
    last_seen_times.clear()
    for j, zone in enumerate(zones):
        zones[j] = (zone[0], zone[1], zone[2], zone[3], False)

# Function to be called from app.py to set max_time_in_zone
def set_max_time_in_zone(max_time):
    global max_time_in_zone
    max_time_in_zone = max_time