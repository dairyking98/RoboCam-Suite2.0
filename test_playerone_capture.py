import os
import sys
import time
import platform
from pathlib import Path
import ctypes
import numpy as np
import cv2

def test_capture():
    print("=== Player One Camera Barebones Capture Test ===")
    
    # 1. Setup SDK Path
    project_root = Path(__file__).resolve().parent
    vendor_dir = project_root / "vendor" / "playerone"
    if str(vendor_dir) not in sys.path:
        sys.path.insert(0, str(vendor_dir))
    
    try:
        print(f"Loading library from: {vendor_dir}")
        # Explicitly check for file existence again to be sure
        lib_name = "libPlayerOneCamera.so" if platform.system() == "Linux" else "PlayerOneCamera.dll"
        lib_path = vendor_dir / lib_name
        if not lib_path.exists():
            print(f"ERROR: Library file NOT FOUND at {lib_path}")
            # Try to list files again
            print(f"Folder contents: {[f.name for f in vendor_dir.iterdir()]}")
            return
            
        # Architecture check on Linux
        if platform.system() == "Linux":
            import subprocess
            print("--- Architecture & Dependencies Diagnostic ---")
            try:
                print(f"Architecture of {lib_name}:")
                subprocess.run(["file", str(lib_path)], check=True)
                print("\nDependencies (ldd):")
                subprocess.run(["ldd", str(lib_path)], check=True)
            except Exception as de:
                print(f"Diagnostic failed: {de}")
            print("----------------------------------------------")

        import pyPOACamera as poa
        print("SDK: pyPOACamera imported successfully.")
    except Exception as e:
        print(f"SDK Error: Could not import pyPOACamera: {e}")
        import traceback
        traceback.print_exc()
        return

    # 2. Detect Camera (with retry loop)
    print("Hardware: Searching for Player One cameras...")
    for attempt in range(5):
        count = poa.GetCameraCount()
        if count > 0:
            break
        print(f"  Attempt {attempt+1}: No cameras found, retrying...")
        time.sleep(1.0)
    
    print(f"Hardware: Found {count} Player One camera(s).")
    if count == 0:
        print("TIP: Ensure the camera is plugged in and the 'libPlayerOneCamera.so' is compatible with your architecture.")
        print(f"Current Architecture: {platform.machine()}")
        return

    # 3. Connect to first camera
    cam_index = 0
    err, props = poa.GetCameraProperties(cam_index)
    if err != poa.POAErrors.POA_OK:
        print(f"Error: GetCameraProperties failed with code {err}")
        return
    
    cam_id = props.cameraID
    model = props.cameraModelName.decode(errors="replace").strip()
    print(f"Connecting to: {model} (ID: {cam_id})")
    
    if poa.OpenCamera(cam_id) != poa.POAErrors.POA_OK:
        print("Error: OpenCamera failed.")
        return
    
    if poa.InitCamera(cam_id) != poa.POAErrors.POA_OK:
        print("Error: InitCamera failed.")
        poa.CloseCamera(cam_id)
        return

    print("Camera: Opened and Initialized.")

    try:
        # 4. Configure
        width, height = props.maxWidth, props.maxHeight
        print(f"Resolution: Setting to {width}x{height}")
        poa.SetImageSize(cam_id, width, height)
        
        # Use RAW8 for simplicity
        poa.SetImageFormat(cam_id, poa.POAImgFormat.POA_RAW8)
        
        # Set exposure and gain
        poa.SetExp(cam_id, 50000, False) # 50ms
        poa.SetGain(cam_id, 100, False)
        
        # 5. Start Capture (Video Mode)
        print("Capture: Starting video mode...")
        if poa.StartExposure(cam_id, False) != poa.POAErrors.POA_OK:
            print("Error: StartExposure failed.")
            return

        # 6. Capture a few frames
        print("Capture: Taking 5 test frames...")
        buf = np.zeros(width * height, dtype=np.uint8)
        
        for i in range(5):
            # Wait for image
            deadline = time.monotonic() + 2.0
            ready = False
            while time.monotonic() < deadline:
                err, ready = poa.ImageReady(cam_id)
                if err == poa.POAErrors.POA_OK and ready:
                    break
                time.sleep(0.01)
            
            if ready:
                err = poa.GetImageData(cam_id, buf, 1000)
                if err == poa.POAErrors.POA_OK:
                    print(f"  Frame {i+1}: Success! Data received.")
                    # Save frame 0 as an image
                    if i == 0:
                        img_path = "test_frame.png"
                        # Simple grayscale save for debug
                        frame_reshaped = buf.reshape((height, width))
                        cv2.imwrite(img_path, frame_reshaped)
                        print(f"  Saved first frame to {img_path}")
                else:
                    print(f"  Frame {i+1}: GetImageData failed (Error {err})")
            else:
                print(f"  Frame {i+1}: Timeout waiting for ImageReady")
            
            time.sleep(0.1)

        # 7. Test Video Recording (using OpenCV VideoWriter)
        print("Video: Testing 2-second recording...")
        video_path = "test_video.avi"
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        out = cv2.VideoWriter(video_path, fourcc, 10.0, (width, height), False)
        
        start_time = time.time()
        frames_recorded = 0
        while time.time() - start_time < 2.0:
            err, ready = poa.ImageReady(cam_id)
            if err == poa.POAErrors.POA_OK and ready:
                if poa.GetImageData(cam_id, buf, 1000) == poa.POAErrors.POA_OK:
                    frame_reshaped = buf.reshape((height, width))
                    out.write(frame_reshaped)
                    frames_recorded += 1
            time.sleep(0.01)
        
        out.release()
        print(f"Video: Recorded {frames_recorded} frames to {video_path}")

        # 8. Stop
        poa.StopExposure(cam_id)
        print("Capture: Stopped.")

    finally:
        poa.CloseCamera(cam_id)
        print("Camera: Closed.")

if __name__ == "__main__":
    test_capture()
