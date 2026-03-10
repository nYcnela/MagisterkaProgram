#!/usr/bin/env python3
"""
Wyliczanie kątów wg Vicon Plug-in Gait metodologii - WERSJA V3 (bez per-person calibration).

Kluczowe konwencje Vicon Plug-in Gait:
- Układ globalny: X=przód, Y=lewo, Z=góra (prawoskrętny)
- Sekwencja Cardan/Euler: YXZ dla większości stawów (flexion, adduction, rotation)
- Kąty są liczone jako rotacja segmentu dystalnego względem proksymalnego

=== WŁASNA DEFINICJA KĄTÓW GŁOWY ===
  HeadAngles_X = PITCH (kiwanie przód-tył)
    - Definicja: arcsin(-X_head.z) gdzie X_head = oś "do przodu" głowy
    - Interpretacja: (+) = głowa pochylona DO PRZODU (ukłon!)
                     (-) = głowa odchylona DO TYŁU

  HeadAngles_Y = ROLL (przechylenie na bok)
    - Definicja: arctan2(Y_head.z, Z_head.z)
    - Interpretacja: (+) = głowa przechylona W PRAWO (prawe ucho do ramienia)
                     (-) = głowa przechylona W LEWO

  HeadAngles_Z = YAW (obrót w poziomie)
    - Definicja: arctan2(X_head.y, X_head.x)
    - Interpretacja: kierunek patrzenia w płaszczyźnie XY
"""

import argparse
import csv
import traceback
from pathlib import Path
from typing import Dict, Tuple, Optional

import numpy as np


# --------------------------------------------------------------------------
# UNIWERSALNE OFFSETY (bez różnicowania per-osoba)
# --------------------------------------------------------------------------
UNIVERSAL_OFFSETS = {
    'LElbowAngles_X': 5.0,
    'RElbowAngles_X': 11.5,
    'RKneeAngles_X': 0.0,
    'LShoulderAngles_X': -20.0,
    'RShoulderAngles_X': -26.0,
    'RShoulderAngles_Y': 0.0,
    'LPelvisAngles_Z': 0.0,
    'LHeadAngles_X': 0.0, 
    'LHipAngles_Y': 8.5,
    'RHipAngles_Y': 8.5,
}


def get_universal_offset(angle_name: str, default: float = 0.0) -> float:
    """Zwraca uniwersalny offset dla danego kąta."""
    return UNIVERSAL_OFFSETS.get(angle_name, default)


# --------------------------------------------------------------------------
# FUNKCJE POMOCNICZE - GEOMETRIA
# --------------------------------------------------------------------------

def normalize(v: np.ndarray) -> np.ndarray:
    """Normalizuje wektor."""
    norm = np.linalg.norm(v)
    if norm < 1e-10:
        return v
    return v / norm


def cross_normalize(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cross product + normalizacja."""
    return normalize(np.cross(a, b))


def gram_schmidt_orthonormalize(v1: np.ndarray, v2: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Gram-Schmidt orthonormalization: zwraca dwa ortogonalne wersory,
    gdzie v1_orth jest równoległy do v1.
    """
    v1_norm = normalize(v1)
    v2_orth = v2 - np.dot(v2, v1_norm) * v1_norm
    v2_norm = normalize(v2_orth)
    return v1_norm, v2_norm


def euler_yxz_from_rotation_matrix(R: np.ndarray) -> np.ndarray:
    """
    Wydobywa kąty Cardan YXZ z macierzy rotacji.

    R = Ry(θy) * Rx(θx) * Rz(θz)

    Zwraca: [θy, θx, θz] w stopniach
    """
    # Sprawdź gimbal lock (|R[1,2]| ≈ 1)
    if abs(R[1, 2]) > 0.9999:
        theta_x = -np.arcsin(np.clip(R[1, 2], -1, 1))
        theta_y = np.arctan2(-R[2, 0], R[0, 0])
        theta_z = 0.0
    else:
        theta_x = -np.arcsin(np.clip(R[1, 2], -1, 1))
        theta_y = np.arctan2(R[0, 2], R[2, 2])
        theta_z = np.arctan2(R[1, 0], R[1, 1])

    return np.degrees([theta_y, theta_x, theta_z])


def euler_zxy_from_rotation_matrix(R: np.ndarray) -> np.ndarray:
    """
    Wydobywa kąty Cardan ZXY z macierzy rotacji (dla pelvis).

    R = Rz(θz) * Rx(θx) * Ry(θy)

    Zwraca: [θz, θx, θy] w stopniach
    """
    if abs(R[2, 1]) > 0.9999:
        theta_x = np.arcsin(np.clip(R[2, 1], -1, 1))
        theta_z = np.arctan2(-R[0, 2], R[0, 0])
        theta_y = 0.0
    else:
        theta_x = np.arcsin(np.clip(R[2, 1], -1, 1))
        theta_z = np.arctan2(-R[0, 1], R[1, 1])
        theta_y = np.arctan2(-R[2, 0], R[2, 2])

    return np.degrees([theta_z, theta_x, theta_y])


# --------------------------------------------------------------------------
# ESTYMACJA JOINT CENTERS (wg Davis/Bell method)
# --------------------------------------------------------------------------

def estimate_hip_joint_centers(lasi: np.ndarray, rasi: np.ndarray,
                               lpsi: np.ndarray, rpsi: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Estymuje centra stawów biodrowych (HJC) wg metody Davis/Bell."""
    asis_mid = (lasi + rasi) / 2.0
    sacr = (lpsi + rpsi) / 2.0
    pw = np.linalg.norm(rasi - lasi)

    pelvis_y = normalize(lasi - rasi)  # w lewo
    sacr_to_asis = asis_mid - sacr
    pelvis_x_temp = cross_normalize(pelvis_y, sacr_to_asis)
    pelvis_z = cross_normalize(pelvis_x_temp, pelvis_y)
    pelvis_x = cross_normalize(pelvis_y, pelvis_z)

    offset_x = -0.19 * pw
    offset_z = -0.36 * pw
    offset_y_l = 0.36 * pw
    offset_y_r = -0.36 * pw

    lhjc = asis_mid + offset_x * pelvis_x + offset_y_l * pelvis_y + offset_z * pelvis_z
    rhjc = asis_mid + offset_x * pelvis_x + offset_y_r * pelvis_y + offset_z * pelvis_z
    return lhjc, rhjc


# --------------------------------------------------------------------------
# BUDOWA SEGMENT COORDINATE SYSTEMS (wg Vicon Plug-in Gait)
# --------------------------------------------------------------------------

def build_pelvis_frame(lasi: np.ndarray, rasi: np.ndarray,
                       lpsi: np.ndarray, rpsi: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Buduje układ współrzędnych miednicy wg Vicon Plug-in Gait."""
    origin = (lasi + rasi) / 2.0
    sacr = (lpsi + rpsi) / 2.0

    y_raw = lasi - rasi
    sacr_to_origin = origin - sacr

    z = cross_normalize(sacr_to_origin, y_raw)
    y = cross_normalize(z, sacr_to_origin)
    x = cross_normalize(y, z)

    frame = np.column_stack([x, y, z])
    return origin, frame


def build_femur_frame(hjc: np.ndarray, kjc: np.ndarray,
                      thigh_marker: np.ndarray, side: str = 'L') -> Tuple[np.ndarray, np.ndarray]:
    """Buduje układ uda (femur) wg Vicon."""
    origin = kjc
    z = normalize(hjc - kjc)
    knee_ref = thigh_marker - kjc
    y_temp = knee_ref - np.dot(knee_ref, z) * z
    y = normalize(y_temp)
    x = cross_normalize(y, z)
    frame = np.column_stack([x, y, z])
    return origin, frame


def build_tibia_frame(kjc: np.ndarray, ajc: np.ndarray,
                      ankle_marker: np.ndarray, side: str = 'L') -> Tuple[np.ndarray, np.ndarray]:
    """Buduje układ goleni (tibia) wg Vicon."""
    origin = ajc
    z = normalize(kjc - ajc)
    ankle_ref = ankle_marker - ajc
    y_temp = ankle_ref - np.dot(ankle_ref, z) * z
    y = normalize(y_temp)
    x = cross_normalize(y, z)
    frame = np.column_stack([x, y, z])
    return origin, frame


def build_foot_frame(heel: np.ndarray, toe: np.ndarray,
                     ankle_marker: np.ndarray, tibia_y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Buduje układ stopy wg Vicon (uproczony, stabilny)."""
    origin = (heel + toe) / 2.0
    foot_vec = toe - heel
    foot_vec_proj = np.array([foot_vec[0], foot_vec[1], 0.0])
    x = normalize(foot_vec_proj)

    z_temp = np.array([0.0, 0.0, 1.0])
    y = cross_normalize(z_temp, x)
    z = cross_normalize(x, y)

    frame = np.column_stack([x, y, z])
    return origin, frame


def build_thorax_frame(c7: np.ndarray, t10: np.ndarray,
                       clav: np.ndarray, strn: np.ndarray,
                       lsho: np.ndarray, rsho: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Buduje układ klatki piersiowej (thorax) wg Vicon."""
    origin = (c7 + t10) / 2.0
    z_raw = c7 - t10
    y_raw = lsho - rsho

    z = normalize(z_raw)
    y_temp = y_raw - np.dot(y_raw, z) * z
    y = normalize(y_temp)
    x = cross_normalize(y, z)

    frame = np.column_stack([x, y, z])
    return origin, frame


def build_upper_arm_frame(shoulder_jc: np.ndarray, elbow_jc: np.ndarray,
                          wrist: np.ndarray, side: str = 'L') -> Tuple[np.ndarray, np.ndarray]:
    """Buduje układ ramienia (humerus) wg Vicon."""
    origin = elbow_jc
    z = normalize(shoulder_jc - elbow_jc)
    forearm_vec = wrist - elbow_jc
    y_temp = cross_normalize(z, forearm_vec)
    if side == 'R':
        y_temp = -y_temp
    y = normalize(y_temp)
    x = cross_normalize(y, z)
    frame = np.column_stack([x, y, z])
    return origin, frame


def build_forearm_frame(elbow_jc: np.ndarray, wrist_jc: np.ndarray,
                        elbow_marker: np.ndarray, side: str = 'L') -> Tuple[np.ndarray, np.ndarray]:
    """Buduje układ przedramienia (radius) wg Vicon."""
    origin = wrist_jc
    z = normalize(elbow_jc - wrist_jc)
    elbow_ref = elbow_marker - wrist_jc
    y_temp = elbow_ref - np.dot(elbow_ref, z) * z
    y = normalize(y_temp)
    if side == 'R':
        y = -y
    x = cross_normalize(y, z)
    frame = np.column_stack([x, y, z])
    return origin, frame


def build_head_frame(lfhd: np.ndarray, rfhd: np.ndarray,
                     lbhd: np.ndarray, rbhd: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Buduje układ głowy wg Vicon (X: back->front, Y: right->left, Z: X×Y)."""
    origin = (lfhd + rfhd + lbhd + rbhd) / 4.0
    front_mid = (lfhd + rfhd) / 2.0
    back_mid = (lbhd + rbhd) / 2.0

    x_raw = front_mid - back_mid
    x = normalize(x_raw)

    y_raw = lfhd - rfhd
    y_temp = y_raw - np.dot(y_raw, x) * x
    y = normalize(y_temp)

    z = cross_normalize(x, y)
    frame = np.column_stack([x, y, z])
    return origin, frame


# --------------------------------------------------------------------------
# OBLICZANIE KĄTÓW STAWOWYCH
# --------------------------------------------------------------------------

def calculate_joint_angles_yxz(proximal_frame: np.ndarray, distal_frame: np.ndarray) -> np.ndarray:
    """R = proximal^T * distal; zwraca [flexion, adduction, rotation] w stopniach (Cardan YXZ)."""
    R = proximal_frame.T @ distal_frame
    return euler_yxz_from_rotation_matrix(R)


def calculate_pelvis_angles(pelvis_frame: np.ndarray) -> np.ndarray:
    """Kąty miednicy względem LAB (Vicon ZXY, mapowanie na X/Y/Z Vicon)."""
    angles_zxy = euler_zxy_from_rotation_matrix(pelvis_frame)
    tilt = angles_zxy[2]
    obliquity = angles_zxy[1]
    rotation = angles_zxy[0]
    return np.array([obliquity, tilt, rotation])


# --------------------------------------------------------------------------
# PROGRESSION FRAME 
# --------------------------------------------------------------------------

def compute_static_progression_frame(markers: Dict[str, np.ndarray]) -> np.ndarray:
    """
    Buduje statyczny Progression Frame dla całego triala:
    - jeśli displacement pelvis (XY) jest znaczący -> kierunek z przemieszczenia
    - jeśli displacement mały -> kierunek z facing pelvis w środkowych 10% triala
    """
    lasi_all = markers['LASI']
    rasi_all = markers['RASI']
    lpsi_all = markers['LPSI']
    rpsi_all = markers['RPSI']

    n_frames = len(lasi_all)
    pelvis_origin_all = (lasi_all + rasi_all) / 2.0

    # 1) displacement (XY) start->end
    disp = pelvis_origin_all[-1] - pelvis_origin_all[0]
    disp_xy = np.array([disp[0], disp[1], 0.0])
    disp_xy_len = float(np.linalg.norm(disp_xy))

    # próg: w mm (Vicon zwykle mm). Jeśli masz metry, podnieś próg w górę.
    DISPLACEMENT_THRESHOLD = 200.0  # 20 cm w mm
    if disp_xy_len > DISPLACEMENT_THRESHOLD:
        progress_x = normalize(disp_xy)
    else:
        # 2) facing z middle 10% triala (jak Vicon, gdy displacement mały)
        mid_start = int(n_frames * 0.45)
        mid_end = int(n_frames * 0.55)
        if mid_end <= mid_start:
            mid_start, mid_end = 0, min(10, n_frames)

        forward_sum = np.zeros(3)
        for i in range(mid_start, mid_end):
            asis_mid = (lasi_all[i] + rasi_all[i]) / 2.0
            sacr_mid = (lpsi_all[i] + rpsi_all[i]) / 2.0
            forward_raw = asis_mid - sacr_mid
            forward_sum += np.array([forward_raw[0], forward_raw[1], 0.0])

        progress_x = normalize(forward_sum)

        # awaryjnie: jeśli forward_sum wyszedł blisko 0
        if np.linalg.norm(progress_x) < 1e-8:
            progress_x = np.array([1.0, 0.0, 0.0])

    progress_z = np.array([0.0, 0.0, 1.0])
    progress_y = cross_normalize(progress_z, progress_x)
    progress_x = cross_normalize(progress_y, progress_z)  # dociśnij ortonormalność

    return np.column_stack([progress_x, progress_y, progress_z])


# --------------------------------------------------------------------------
# WCZYTYWANIE I PARSOWANIE CSV
# --------------------------------------------------------------------------

def find_section_by_name(lines: list, section_name: str) -> int:
    for i, line in enumerate(lines):
        if line.strip().startswith(section_name):
            return i
    return -1


def parse_marker_names(marker_line: str) -> list:
    parts = marker_line.strip().split(';')
    markers = []
    for i in range(2, len(parts), 3):
        name = parts[i].strip()
        if ':' in name:
            name = name.split(':')[1]
        markers.append(name)
    return markers


def load_trajectories(csv_path: Path) -> Tuple[np.ndarray, list, int]:
    lines = csv_path.read_text(encoding='utf-8').splitlines()

    traj_start = find_section_by_name(lines, 'Trajectories')
    if traj_start == -1:
        raise ValueError("Nie znaleziono sekcji 'Trajectories'")

    fps_line = lines[traj_start + 1].strip()
    fps = int(fps_line.split(';')[0])

    marker_names = parse_marker_names(lines[traj_start + 2])
    data_start = traj_start + 5

    data_end = len(lines)
    for i in range(data_start, len(lines)):
        if not lines[i].strip() or lines[i].count(';') < 10:
            data_end = i
            break

    data_lines = lines[data_start:data_end]
    rows = []
    for line in data_lines:
        parts = line.strip().split(';')
        if len(parts) < 3:
            continue
        rows.append([float(x) if x else np.nan for x in parts])

    data = np.array(rows)
    return data, marker_names, fps


def extract_marker_xyz(data: np.ndarray, marker_names: list, marker: str) -> np.ndarray:
    try:
        idx = marker_names.index(marker)
    except ValueError:
        raise ValueError(f"Marker '{marker}' nie znaleziony")

    x_col = 2 + idx * 3
    y_col = x_col + 1
    z_col = x_col + 2
    return data[:, [x_col, y_col, z_col]]


# --------------------------------------------------------------------------
# GŁÓWNA FUNKCJA - WYLICZANIE WSZYSTKICH KĄTÓW WG VICON
# --------------------------------------------------------------------------

def calculate_all_angles_vicon(traj_data: np.ndarray, marker_names: list,
                               filename: Optional[str] = None) -> Dict[str, np.ndarray]:
    n_frames = len(traj_data)

    marker_list = [
        'LFHD', 'RFHD', 'LBHD', 'RBHD', 'C7', 'T10', 'CLAV', 'STRN',
        'LSHO', 'RSHO', 'LELB', 'RELB', 'LWRA', 'RWRA', 'LWRB', 'RWRB',
        'LASI', 'RASI', 'LPSI', 'RPSI',
        'LTHI', 'RTHI', 'LKNE', 'RKNE', 'LTIB', 'RTIB',
        'LANK', 'RANK', 'LHEE', 'RHEE', 'LTOE', 'RTOE'
    ]

    markers: Dict[str, np.ndarray] = {}
    for m in marker_list:
        try:
            markers[m] = extract_marker_xyz(traj_data, marker_names, m)
        except ValueError:
            markers[m] = np.zeros((n_frames, 3))
            print(f"  Uwaga: Marker {m} nie znaleziony, używam zer")

    angles = {
        'LKneeAngles_X': np.zeros(n_frames),
        'LKneeAngles_Y': np.zeros(n_frames),
        'LKneeAngles_Z': np.zeros(n_frames),
        'RKneeAngles_X': np.zeros(n_frames),
        'RKneeAngles_Y': np.zeros(n_frames),
        'RKneeAngles_Z': np.zeros(n_frames),
        'LHipAngles_X': np.zeros(n_frames),
        'LHipAngles_Y': np.zeros(n_frames),
        'LHipAngles_Z': np.zeros(n_frames),
        'RHipAngles_X': np.zeros(n_frames),
        'RHipAngles_Y': np.zeros(n_frames),
        'RHipAngles_Z': np.zeros(n_frames),
        'LAnkleAngles_X': np.zeros(n_frames),
        'LAnkleAngles_Y': np.zeros(n_frames),
        'LAnkleAngles_Z': np.zeros(n_frames),
        'RAnkleAngles_X': np.zeros(n_frames),
        'RAnkleAngles_Y': np.zeros(n_frames),
        'RAnkleAngles_Z': np.zeros(n_frames),
        'LPelvisAngles_X': np.zeros(n_frames),
        'LPelvisAngles_Y': np.zeros(n_frames),
        'LPelvisAngles_Z': np.zeros(n_frames),
        'LShoulderAngles_X': np.zeros(n_frames),
        'LShoulderAngles_Y': np.zeros(n_frames),
        'LShoulderAngles_Z': np.zeros(n_frames),
        'RShoulderAngles_X': np.zeros(n_frames),
        'RShoulderAngles_Y': np.zeros(n_frames),
        'RShoulderAngles_Z': np.zeros(n_frames),
        'LElbowAngles_X': np.zeros(n_frames),
        'LElbowAngles_Y': np.zeros(n_frames),
        'LElbowAngles_Z': np.zeros(n_frames),
        'RElbowAngles_X': np.zeros(n_frames),
        'RElbowAngles_Y': np.zeros(n_frames),
        'RElbowAngles_Z': np.zeros(n_frames),
        'LHeadAngles_X': np.zeros(n_frames),
        'LHeadAngles_Y': np.zeros(n_frames),
        'LHeadAngles_Z': np.zeros(n_frames),
        'RHeadAngles_X': np.zeros(n_frames),
        'RHeadAngles_Y': np.zeros(n_frames),
        'RHeadAngles_Z': np.zeros(n_frames),
    }

    # =================================================================
    # STATIC PROGRESSION FRAME
    # =================================================================
    progression_frame_static = compute_static_progression_frame(markers)

    for i in range(n_frames):
        # =============================================================
        # PELVIS
        # =============================================================
        lasi = markers['LASI'][i]
        rasi = markers['RASI'][i]
        lpsi = markers['LPSI'][i]
        rpsi = markers['RPSI'][i]

        lhjc, rhjc = estimate_hip_joint_centers(lasi, rasi, lpsi, rpsi)
        pelvis_origin, pelvis_frame = build_pelvis_frame(lasi, rasi, lpsi, rpsi)

        pelvis_angles = calculate_pelvis_angles(pelvis_frame)
        angles['LPelvisAngles_X'][i] = pelvis_angles[0]  
        angles['LPelvisAngles_Y'][i] = pelvis_angles[1]  # Tilt
        angles['LPelvisAngles_Z'][i] = -pelvis_angles[2]  # Rotation

        # =============================================================
        # LEFT LEG
        # =============================================================
        lkne = markers['LKNE'][i]
        lank = markers['LANK'][i]
        lhee = markers['LHEE'][i]
        ltoe = markers['LTOE'][i]
        lthi = markers['LTHI'][i]

        lkjc = lkne.copy()
        lajc = lank.copy()

        _, lfemur_frame = build_femur_frame(lhjc, lkjc, lthi, side='L')
        _, ltibia_frame = build_tibia_frame(lkjc, lajc, lank, side='L')
        _, lfoot_frame = build_foot_frame(lhee, ltoe, lank, ltibia_frame[:, 1])

        lhip_angles = calculate_joint_angles_yxz(pelvis_frame, lfemur_frame)
        angles['LHipAngles_X'][i] = lhip_angles[0]
        lhip_y_offset = get_universal_offset('LHipAngles_Y', 8.5)
        angles['LHipAngles_Y'][i] = -lhip_angles[1] * 1.4 + lhip_y_offset
        angles['LHipAngles_Z'][i] = lhip_angles[2]

        lknee_angles = calculate_joint_angles_yxz(lfemur_frame, ltibia_frame)
        angles['LKneeAngles_X'][i] = lknee_angles[0]
        angles['LKneeAngles_Y'][i] = lknee_angles[1]
        angles['LKneeAngles_Z'][i] = lknee_angles[2]

        lankle_angles = calculate_joint_angles_yxz(ltibia_frame, lfoot_frame)
        angles['LAnkleAngles_X'][i] = lankle_angles[0]
        angles['LAnkleAngles_Y'][i] = lankle_angles[1]
        angles['LAnkleAngles_Z'][i] = lankle_angles[2]

        # =============================================================
        # RIGHT LEG
        # =============================================================
        rkne = markers['RKNE'][i]
        rank = markers['RANK'][i]
        rhee = markers['RHEE'][i]
        rtoe = markers['RTOE'][i]
        rthi = markers['RTHI'][i]

        rkjc = rkne.copy()
        rajc = rank.copy()

        _, rfemur_frame = build_femur_frame(rhjc, rkjc, rthi, side='R')
        _, rtibia_frame = build_tibia_frame(rkjc, rajc, rank, side='R')
        _, rfoot_frame = build_foot_frame(rhee, rtoe, rank, rtibia_frame[:, 1])

        rhip_angles = calculate_joint_angles_yxz(pelvis_frame, rfemur_frame)
        angles['RHipAngles_X'][i] = rhip_angles[0]
        rhip_y_offset = get_universal_offset('RHipAngles_Y', 8.5)
        angles['RHipAngles_Y'][i] = rhip_angles[1] * 1.4 + rhip_y_offset
        angles['RHipAngles_Z'][i] = -rhip_angles[2]

        rknee_angles = calculate_joint_angles_yxz(rfemur_frame, rtibia_frame)
        rknee_x_offset = get_universal_offset('RKneeAngles_X', 0.0)
        angles['RKneeAngles_X'][i] = -rknee_angles[0] + rknee_x_offset
        angles['RKneeAngles_Y'][i] = -rknee_angles[1]
        angles['RKneeAngles_Z'][i] = -rknee_angles[2]

        rankle_angles = calculate_joint_angles_yxz(rtibia_frame, rfoot_frame)
        angles['RAnkleAngles_X'][i] = rankle_angles[0]
        angles['RAnkleAngles_Y'][i] = -rankle_angles[1]
        angles['RAnkleAngles_Z'][i] = -rankle_angles[2]

        # =============================================================
        # UPPER BODY
        # =============================================================
        c7 = markers['C7'][i]
        t10 = markers['T10'][i]
        clav = markers['CLAV'][i]
        strn = markers['STRN'][i]
        lsho = markers['LSHO'][i]
        rsho = markers['RSHO'][i]
        lelb = markers['LELB'][i]
        relb = markers['RELB'][i]
        lwra = markers['LWRA'][i]
        rwra = markers['RWRA'][i]

        _, thorax_frame = build_thorax_frame(c7, t10, clav, strn, lsho, rsho)

        # SHOULDERS
        lsjc = lsho.copy()
        lejc = lelb.copy()
        _, luarm_frame = build_upper_arm_frame(lsjc, lejc, lwra, side='L')

        lshoulder_angles = calculate_joint_angles_yxz(thorax_frame, luarm_frame)
        lsho_x_offset = get_universal_offset('LShoulderAngles_X', -20.0)
        angles['LShoulderAngles_X'][i] = -lshoulder_angles[0] * 0.81 + lsho_x_offset
        angles['LShoulderAngles_Y'][i] = lshoulder_angles[1]
        angles['LShoulderAngles_Z'][i] = lshoulder_angles[2]

        rsjc = rsho.copy()
        rejc = relb.copy()
        _, ruarm_frame = build_upper_arm_frame(rsjc, rejc, rwra, side='R')

        rshoulder_angles = calculate_joint_angles_yxz(thorax_frame, ruarm_frame)
        rsho_x_offset = get_universal_offset('RShoulderAngles_X', -26.0)
        rsho_y_offset = get_universal_offset('RShoulderAngles_Y', 0.0)
        angles['RShoulderAngles_X'][i] = -rshoulder_angles[0] * 0.85 + rsho_x_offset
        angles['RShoulderAngles_Y'][i] = -rshoulder_angles[1] + rsho_y_offset
        angles['RShoulderAngles_Z'][i] = -rshoulder_angles[2]

        # ELBOWS
        lwrb = markers['LWRB'][i]
        rwrb = markers['RWRB'][i]
        lwjc = (lwra + lwrb) / 2.0
        rwjc = (rwra + rwrb) / 2.0

        _, lfarm_frame = build_forearm_frame(lejc, lwjc, lelb, side='L')
        lelbow_angles = calculate_joint_angles_yxz(luarm_frame, lfarm_frame)
        lelbow_x_offset = get_universal_offset('LElbowAngles_X', 5.0)
        angles['LElbowAngles_X'][i] = -lelbow_angles[0] + lelbow_x_offset
        angles['LElbowAngles_Y'][i] = lelbow_angles[1]
        angles['LElbowAngles_Z'][i] = lelbow_angles[2]

        _, rfarm_frame = build_forearm_frame(rejc, rwjc, relb, side='R')
        relbow_angles = calculate_joint_angles_yxz(ruarm_frame, rfarm_frame)
        relbow_x_offset = get_universal_offset('RElbowAngles_X', 11.5)
        angles['RElbowAngles_X'][i] = relbow_angles[0] * 0.85 + relbow_x_offset
        angles['RElbowAngles_Y'][i] = -relbow_angles[1]
        angles['RElbowAngles_Z'][i] = -relbow_angles[2]

        # =============================================================
        # HEAD 
        # =============================================================
        # Prosta i intuicyjna definicja kątów głowy względem LABORATORIUM:
        #   X = PITCH (kiwanie przód-tył) - ukłony!
        #   Y = ROLL  (przechylenie na bok)
        #   Z = YAW   (obrót w poziomie)
        # =============================================================
        lfhd = markers['LFHD'][i]
        rfhd = markers['RFHD'][i]
        lbhd = markers['LBHD'][i]
        rbhd = markers['RBHD'][i]
        _, head_frame = build_head_frame(lfhd, rfhd, lbhd, rbhd)

        # osie głowy
        x_head = head_frame[:, 0]  # oś "do przodu" głowy
        y_head = head_frame[:, 1]  # oś "w lewo" głowy
        z_head = head_frame[:, 2]  # oś "do góry" głowy

        # PITCH = arcsin(-X_head.z)
        # (+) = głowa pochylona DO PRZODU (ukłon!)
        # (-) = głowa odchylona DO TYŁU
        head_pitch = np.degrees(np.arcsin(np.clip(-x_head[2], -1.0, 1.0)))

        # ROLL = arctan2(Y_head.z, Z_head.z)
        # (+) = głowa przechylona W PRAWO
        # (-) = głowa przechylona W LEWO
        head_roll = np.degrees(np.arctan2(y_head[2], z_head[2]))

        # YAW = arctan2(X_head.y, X_head.x)
        # Kierunek patrzenia w płaszczyźnie poziomej
        head_yaw = np.degrees(np.arctan2(x_head[1], x_head[0]))

        # Zapisz kąty
        angles['LHeadAngles_X'][i] = head_pitch  # PITCH - ukłony
        angles['LHeadAngles_Y'][i] = head_roll   # ROLL
        angles['LHeadAngles_Z'][i] = head_yaw    # YAW

        # R = L (głowa jest symetryczna)
        angles['RHeadAngles_X'][i] = head_pitch
        angles['RHeadAngles_Y'][i] = head_roll
        angles['RHeadAngles_Z'][i] = head_yaw

    # =================================================================
    # POST-PROCESSING: Naprawa skoków (tylko tam gdzie ma sens)
    # =================================================================
    def fix_gimbal_jumps(angle_array, jump_threshold=50.0):
        if len(angle_array) < 5:
            return angle_array
        result = angle_array.copy()

        jumps = []
        for j in range(1, len(result)):
            if abs(result[j] - result[j - 1]) > jump_threshold:
                jumps.append(j)
        if not jumps:
            return result

        segments = []
        current = [jumps[0]]
        for j in jumps[1:]:
            if j - current[-1] <= 30:
                current.append(j)
            else:
                segments.append(current)
                current = [j]
        segments.append(current)

        for seg in segments:
            start_idx = max(0, seg[0] - 1)
            end_idx = min(len(result) - 1, seg[-1] + 1)
            while end_idx < len(result) - 1:
                if abs(result[end_idx + 1] - result[end_idx]) < jump_threshold:
                    break
                end_idx += 1
            if end_idx > start_idx:
                sv = result[start_idx]
                ev = result[end_idx]
                for k in range(start_idx + 1, end_idx):
                    t = (k - start_idx) / (end_idx - start_idx)
                    result[k] = sv + t * (ev - sv)
        return result

    for angle_name in ['LShoulderAngles_X', 'RShoulderAngles_X', 'LElbowAngles_X', 'RElbowAngles_X']:
        angles[angle_name] = fix_gimbal_jumps(angles[angle_name], jump_threshold=50.0)

    # =================================================================
    # UNWRAP dla kątów rotacyjnych (usunięcie skoków przy ±180°)
    # =================================================================
    # Pelvis Z (rotation/yaw) - przy pełnych obrotach przeskakuje z +180° do -180°
    angles['LPelvisAngles_Z'] = np.degrees(np.unwrap(np.radians(angles['LPelvisAngles_Z'])))
    
    # Head Z (yaw) - analogicznie
    angles['LHeadAngles_Z'] = np.degrees(np.unwrap(np.radians(angles['LHeadAngles_Z'])))
    angles['RHeadAngles_Z'] = np.degrees(np.unwrap(np.radians(angles['RHeadAngles_Z'])))

    return angles


# --------------------------------------------------------------------------
# ZAPIS WYNIKU DO CSV
# --------------------------------------------------------------------------

def write_output_csv(input_path: Path, output_path: Path,
                     calculated_angles: Dict[str, np.ndarray],
                     traj_data: np.ndarray, marker_names: list, fps: int):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = len(traj_data)

    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, delimiter=';')

        writer.writerow(['Model Outputs'] + [''] * 79)
        writer.writerow([fps] + [''] * 79)

        angle_names = [
            'hanna_aleksandrowicz:LAbsAnkleAngle', '', '',
            'hanna_aleksandrowicz:LAnkleAngles', '', '',
            'hanna_aleksandrowicz:LElbowAngles', '', '',
            'hanna_aleksandrowicz:LFootProgressAngles', '', '',
            'hanna_aleksandrowicz:LHeadAngles', '', '',
            'hanna_aleksandrowicz:LHipAngles', '', '',
            'hanna_aleksandrowicz:LKneeAngles', '', '',
            'hanna_aleksandrowicz:LNeckAngles', '', '',
            'hanna_aleksandrowicz:LPelvisAngles', '', '',
            'hanna_aleksandrowicz:LShoulderAngles', '', '',
            'hanna_aleksandrowicz:LSpineAngles', '', '',
            'hanna_aleksandrowicz:LThoraxAngles', '', '',
            'hanna_aleksandrowicz:LWristAngles', '', '',
            'hanna_aleksandrowicz:RAbsAnkleAngle', '', '',
            'hanna_aleksandrowicz:RAnkleAngles', '', '',
            'hanna_aleksandrowicz:RElbowAngles', '', '',
            'hanna_aleksandrowicz:RFootProgressAngles', '', '',
            'hanna_aleksandrowicz:RHeadAngles', '', '',
            'hanna_aleksandrowicz:RHipAngles', '', '',
            'hanna_aleksandrowicz:RKneeAngles', '', '',
            'hanna_aleksandrowicz:RNeckAngles', '', '',
            'hanna_aleksandrowicz:RPelvisAngles', '', '',
            'hanna_aleksandrowicz:RShoulderAngles', '', '',
            'hanna_aleksandrowicz:RSpineAngles', '', '',
            'hanna_aleksandrowicz:RThoraxAngles', '', '',
            'hanna_aleksandrowicz:RWristAngles', '', '',
            'hanna_aleksandrowicz:CentreOfMass', '', '',
            'hanna_aleksandrowicz:CentreOfMassFloor', '', '',
        ]
        writer.writerow(['', ''] + angle_names)

        header = ['Frame', 'Sub Frame'] + ['X', 'Y', 'Z'] * 28
        writer.writerow(header)

        units = ['', ''] + ['deg', 'deg', 'deg'] * 26 + ['mm', 'mm', 'mm', 'mm', 'mm', 'mm']
        writer.writerow(units)

        for i in range(n_frames):
            row = [i + 1, 0]

            row += [0, 0, 0]  # LAbsAnkleAngle
            row += [calculated_angles['LAnkleAngles_X'][i], calculated_angles['LAnkleAngles_Y'][i], calculated_angles['LAnkleAngles_Z'][i]]
            row += [calculated_angles['LElbowAngles_X'][i], calculated_angles['LElbowAngles_Y'][i], calculated_angles['LElbowAngles_Z'][i]]
            row += [0, 0, 0]  # LFootProgressAngles
            row += [calculated_angles['LHeadAngles_X'][i], calculated_angles['LHeadAngles_Y'][i], calculated_angles['LHeadAngles_Z'][i]]
            row += [calculated_angles['LHipAngles_X'][i], calculated_angles['LHipAngles_Y'][i], calculated_angles['LHipAngles_Z'][i]]
            row += [calculated_angles['LKneeAngles_X'][i], calculated_angles['LKneeAngles_Y'][i], calculated_angles['LKneeAngles_Z'][i]]
            row += [0, 0, 0]  # LNeckAngles
            row += [calculated_angles['LPelvisAngles_X'][i], calculated_angles['LPelvisAngles_Y'][i], calculated_angles['LPelvisAngles_Z'][i]]
            row += [calculated_angles['LShoulderAngles_X'][i], calculated_angles['LShoulderAngles_Y'][i], calculated_angles['LShoulderAngles_Z'][i]]
            row += [0, 0, 0]  # LSpineAngles
            row += [0, 0, 0]  # LThoraxAngles
            row += [0, 0, 0]  # LWristAngles

            row += [0, 0, 0]  # RAbsAnkleAngle
            row += [calculated_angles['RAnkleAngles_X'][i], calculated_angles['RAnkleAngles_Y'][i], calculated_angles['RAnkleAngles_Z'][i]]
            row += [calculated_angles['RElbowAngles_X'][i], calculated_angles['RElbowAngles_Y'][i], calculated_angles['RElbowAngles_Z'][i]]
            row += [0, 0, 0]  # RFootProgressAngles
            row += [calculated_angles['RHeadAngles_X'][i], calculated_angles['RHeadAngles_Y'][i], calculated_angles['RHeadAngles_Z'][i]]
            row += [calculated_angles['RHipAngles_X'][i], calculated_angles['RHipAngles_Y'][i], calculated_angles['RHipAngles_Z'][i]]
            row += [calculated_angles['RKneeAngles_X'][i], calculated_angles['RKneeAngles_Y'][i], calculated_angles['RKneeAngles_Z'][i]]
            row += [0, 0, 0]  # RNeckAngles
            row += [0, 0, 0]  # RPelvisAngles
            row += [calculated_angles['RShoulderAngles_X'][i], calculated_angles['RShoulderAngles_Y'][i], calculated_angles['RShoulderAngles_Z'][i]]
            row += [0, 0, 0]  # RSpineAngles
            row += [0, 0, 0]  # RThoraxAngles
            row += [0, 0, 0]  # RWristAngles
            row += [0, 0, 0]  # CentreOfMass
            row += [0, 0, 0]  # CentreOfMassFloor

            writer.writerow([f'{x:.6f}' if isinstance(x, (float, np.float64)) else x for x in row])

        # ========== SEKCJA TRAJECTORIES ==========
        input_lines = input_path.read_text(encoding='utf-8').splitlines()
        traj_start = find_section_by_name(input_lines, 'Trajectories')
        if traj_start != -1:
            for line in input_lines[traj_start:]:
                if line.strip():
                    f.write(line + '\n')


# --------------------------------------------------------------------------
# GŁÓWNA PĘTLA
# --------------------------------------------------------------------------

def process_file(input_path: Path, output_root: Path, input_root: Path):
    print(f"Przetwarzanie: {input_path.name}")
    try:
        traj_data, marker_names, fps = load_trajectories(input_path)
        angles = calculate_all_angles_vicon(traj_data, marker_names, input_path.name)

        relative_path = input_path.relative_to(input_root)
        output_path = output_root / relative_path
        write_output_csv(input_path, output_path, angles, traj_data, marker_names, fps)

        print(f"  ✓ Zapisano: {output_path}")
    except Exception as e:
        print(f"  ✗ BŁĄD: {e}")
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(
        description="Wyliczanie kątów wg Vicon Plug-in Gait - POPRAWIONA WERSJA (HeadAngles = Progress Frame)."
    )
    parser.add_argument(
        '--in-root', type=Path, default=Path('../data/csv/raw'),
        help='Katalog wejściowy z plikami CSV Vicon'
    )
    parser.add_argument(
        '--out-root', type=Path, default=Path('../data/csv/manual/calculated'),
        help='Katalog wyjściowy'
    )
    args = parser.parse_args()

    if not args.in_root.is_dir():
        print(f"BŁĄD: Katalog {args.in_root} nie istnieje!")
        return

    csv_files = sorted(args.in_root.rglob('*.csv'))
    if not csv_files:
        print(f"Nie znaleziono plików CSV w {args.in_root}")
        return

    print(f"Znaleziono {len(csv_files)} plików CSV\n")
    for csv_file in csv_files:
        process_file(csv_file, args.out_root, args.in_root)

    print(f"\nGotowe! Wyniki w: {args.out_root}")


if __name__ == '__main__':
    main()
