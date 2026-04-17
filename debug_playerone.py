import os
import sys
import platform
from pathlib import Path
import ctypes

def debug_playerone():
    print(f"Python version: {sys.version}")
    print(f"Platform: {platform.platform()}")
    
    # Project root is the current directory
    project_root = Path(__file__).resolve().parent
    vendor_dir = project_root / "vendor" / "playerone"
    
    print(f"Vendor directory: {vendor_dir}")
    if not vendor_dir.is_dir():
        print("ERROR: Vendor directory not found!")
        return

    print("Vendor directory contents:")
    for f in vendor_dir.iterdir():
        print(f"  - {f.name}")

    # Check for the .so file
    lib_name = "libPlayerOneCamera.so" if platform.system() == "Linux" else "PlayerOneCamera.dll"
    lib_path = vendor_dir / lib_name
    print(f"Checking for library: {lib_path}")
    if lib_path.exists():
        print(f"  EXISTS: {lib_path}")
    else:
        print(f"  MISSING: {lib_path}")

    # Add to sys.path
    if str(vendor_dir) not in sys.path:
        sys.path.insert(0, str(vendor_dir))
        print(f"Added {vendor_dir} to sys.path")

    # Try manual ctypes load
    print(f"Attempting manual ctypes.cdll.LoadLibrary('{lib_path}')...")
    try:
        lib = ctypes.cdll.LoadLibrary(str(lib_path))
        print("SUCCESS: Library loaded via ctypes")
    except Exception as e:
        print(f"FAILED: Library load error: {e}")

    # Try importing the wrapper
    print("Attempting 'import pyPOACamera'...")
    try:
        import pyPOACamera as poa
        print("SUCCESS: pyPOACamera imported")
        
        # Check for SDK version if available
        try:
            version = poa.GetSDKVersion()
            print(f"SDK Version: {version}")
        except Exception as e:
            print(f"SDK Version: Error calling GetSDKVersion: {e}")
            
        count = poa.GetCameraCount()
        print(f"Camera count: {count}")
        
        for i in range(count):
            err, props = poa.GetCameraProperties(i)
            if err == poa.POAErrors.POA_OK:
                model = props.cameraModelName.decode(errors="replace").strip()
                print(f"  Camera {i}: {model}")
            else:
                print(f"  Camera {i}: Error {err}")
                
    except Exception as e:
        print(f"FAILED: Import or SDK error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_playerone()
