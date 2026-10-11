import numpy as np
import cv2

NOSE = 0
LEFT_EYE,RIGHT_EYE= 1 , 2
L_SHOULDER, R_SHOULDER = 5, 6
L_HIP, R_HIP = 11, 12
CONFIDENCE_THRESHOLD = 0.3

def anonymise_event(frame, all_keypoints, boxes, all_conf, person_index):
        poi_bb = boxes[person_index]  # poi_bb is the person of interest bounding box
        poi_kp = all_keypoints[person_index] # poi_kp is the person of interest keypoints 
        poi_conf = all_conf[person_index]
        blur_person(frame=frame, bounding_box=poi_bb, keypoints=poi_kp, conf = poi_conf)
        x1, y1, x2, y2 = poi_bb
        for i in range(len(boxes)):  # This loop checks if there are any other people in the bounding box of the person of interest.
            if i != person_index:
                temp_x1, temp_y1, temp_x2, temp_y2 = boxes[i]
                overlaps = (
                    temp_x1 < x2
                    and temp_x2 > x1
                    and temp_y1 < y2
                    and temp_y2 > y1
                )
                if overlaps:
                    blur_person(frame=frame, bounding_box=boxes[i], keypoints=all_keypoints[i], conf=all_conf[i])

        return frame[y1:y2, x1:x2].copy()

def blur_person(frame, bounding_box, keypoints, conf):
        x1, y1, x2, y2 = bounding_box
        bbox_width, bbox_height = (abs(x2-x1), abs(y2-y1))
        # Check for facial keypoints such as eyes or nose.
        
        face_centre = None 

        body_direction = get_face_direction(keypoints, conf=conf) # The return value can be None or a vector with floating point values. 
        
        face_centre = estimate_from_face_keypoints(keypoints=keypoints, conf=conf) # The return value can be None or a vector with integer values. 

        if face_centre is None and body_direction is not None:
            face_centre = estimate_from_body_keypoints(keypoints=keypoints, conf = conf, body_direction = body_direction)

        if face_centre is not None and body_direction is not None:
            shoulder_width = np.linalg.norm(
                                np.array(keypoints[L_SHOULDER][:2]) -
                                np.array(keypoints[R_SHOULDER][:2])
                            )
            face_radius = max(
                int(0.18 * bbox_width),
                int(0.45 * shoulder_width)
            )
            y_scaler = 1 + abs(body_direction[1])/2
            x_scalar = 1 + abs(body_direction[0])/2
            face_x1 = int(face_centre[0] - (face_radius * x_scalar))
            face_x2 = int(face_centre[0] + (face_radius * x_scalar))
            face_y1 = int(face_centre[1] - (face_radius * y_scaler))
            face_y2 = int(face_centre[1] + (face_radius * y_scaler))

            # Fit the face within the bounding box
            face_x1 = max(face_x1 , x1) 
            face_x2 = min(face_x2, x2)
            face_y1 = max(face_y1, y1)
            face_y2 = min(face_y2, y2)

        else: 
            # Unable to estimate face safely:
            # blur the entire detected person.
            face_x1 = x1
            face_x2 = x2
            face_y1 = y1
            face_y2 = y2

        if face_x2 <= face_x1 or face_y2 <= face_y1: # This ensures we don't apply the Gaussian blur to an empty face region. 
            return
        
        face_width = abs(face_x2-face_x1)
        kernel_size = max(3, int(face_width * 0.5))
        # Gaussian kernel must be odd
        if kernel_size % 2 == 0:
            kernel_size += 1
        sigma = face_width*0.3
        face_region = frame[face_y1:face_y2, face_x1:face_x2]
        blurred_face = cv2.GaussianBlur(
            src=face_region, 
            ksize=(kernel_size, kernel_size),
            sigmaX=sigma, 
            sigmaY=sigma
        )

        frame[face_y1:face_y2, face_x1:face_x2] = blurred_face

def estimate_from_face_keypoints(keypoints, conf):
    nose_kp = keypoints[NOSE]
    l_eye_kp = keypoints[LEFT_EYE]
    r_eye_kp = keypoints[RIGHT_EYE] 
    eye_kp_valid = (conf[LEFT_EYE] > CONFIDENCE_THRESHOLD and conf[RIGHT_EYE] > CONFIDENCE_THRESHOLD)
    if eye_kp_valid:
        eye_mid = np.array([
                            (l_eye_kp[0] + r_eye_kp[0]) / 2,
                            (l_eye_kp[1] + r_eye_kp[1]) / 2
                        ])
        return eye_mid.astype(int)
    if conf[NOSE] > CONFIDENCE_THRESHOLD:
        return np.array(nose_kp).astype(int)
    return None
        
def estimate_from_body_keypoints(keypoints, conf , body_direction):
    shoulder_kp_valid = (conf[L_SHOULDER] > CONFIDENCE_THRESHOLD and conf[R_SHOULDER] > CONFIDENCE_THRESHOLD)
    if shoulder_kp_valid:
        l_shoulder_kp = keypoints[L_SHOULDER] 
        r_shoulder_kp = keypoints[R_SHOULDER]

        shoulder_mid = np.array([
                            (l_shoulder_kp[0] + r_shoulder_kp[0]) / 2,
                            (l_shoulder_kp[1] + r_shoulder_kp[1]) / 2
                        ])
        
        shoulder_distance = np.linalg.norm(
            np.array(r_shoulder_kp[:2]) -
            np.array(l_shoulder_kp[:2])
        )

        head_offset = shoulder_distance * 0.7

        face_centre = shoulder_mid + body_direction * head_offset
        return np.array(face_centre).astype(int)
    return None
    
def get_face_direction(keypoints, conf):
    nose_kp = keypoints[NOSE]

    l_eye_kp = keypoints[LEFT_EYE]
    r_eye_kp = keypoints[RIGHT_EYE] 

    l_hip_kp = keypoints[L_HIP] 
    r_hip_kp = keypoints[R_HIP] 

    l_shoulder_kp = keypoints[L_SHOULDER] 
    r_shoulder_kp = keypoints[R_SHOULDER]

    shoulder_kp_valid = (conf[L_SHOULDER] > CONFIDENCE_THRESHOLD and conf[R_SHOULDER] > CONFIDENCE_THRESHOLD)
    hip_kp_valid = (conf[L_HIP] > CONFIDENCE_THRESHOLD and conf[R_HIP] > CONFIDENCE_THRESHOLD)
    eye_kp_valid = (conf[LEFT_EYE] > CONFIDENCE_THRESHOLD and conf[RIGHT_EYE] > CONFIDENCE_THRESHOLD)

    if shoulder_kp_valid:
        shoulder_mid = np.array([
                    (l_shoulder_kp[0] + r_shoulder_kp[0]) / 2,
                    (l_shoulder_kp[1] + r_shoulder_kp[1]) / 2
                ])
    else:
        return None
    if hip_kp_valid:
        hip_mid = np.array([
            (l_hip_kp[0] + r_hip_kp[0]) / 2,
            (l_hip_kp[1] + r_hip_kp[1]) / 2
        ])

        body_vector = get_unit_vector(shoulder_mid - hip_mid)
        if body_vector is not None:
            return body_vector

    if eye_kp_valid:
        eye_mid = np.array([
                             (l_eye_kp[0] + r_eye_kp[0]) / 2,
                             (l_eye_kp[1] + r_eye_kp[1]) / 2
                         ])
        body_vector = get_unit_vector(eye_mid - shoulder_mid)
        if body_vector is not None:
            return body_vector
    if conf[NOSE] > CONFIDENCE_THRESHOLD:
        body_vector = get_unit_vector(nose_kp - shoulder_mid)
        if body_vector is not None:
            return body_vector

def get_unit_vector(vector):
    vector = np.array(vector)

    # calculate magnitude 
    magnitude = np.linalg.norm(vector)

    if magnitude != 0:
        return vector/magnitude
    
    return None
