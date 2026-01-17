# This is a camera control and capture script that is running on a Raspberry 5 with a ZWO ASI662MC camera
# the system also uses a 480 by 320 screen to output a preview, though the script will be run via ssh


import os, sys
venv = "/home/gandalf/astro/Scripts/.venv"
activate_this = os.path.join(venv, "bin/activate_this.py")
if os.path.exists(activate_this):
	exec(open(activate_this).read(), {'__file__': activate_this})
import zwoasi as asi # type: ignore
import numpy as np # type: ignore
import cv2 # type: ignore
import time
import signal
import select
import glob
from pathlib import Path
import getpass
import asi_helper as helper
from serial.tools import list_ports # type: ignore
import serial # type: ignore

try:
	import tifffile # type: ignore
	TIFF_AVAILABLE = True
except Exception:
	TIFF_AVAILABLE = False

try:
	import tempfile # used to find a writable fallback directory
except Exception:
	# provide a sentinel so name exists and calls can be guarded
	tempfile = None

# Note: temp dir is resolved inline where needed using a small try/fallback to avoid
# NameError if tempfile is missing or throws.



# ---- SET UP ----
BASE_DIR = "/home/gandalf/astro/"
# allow overriding save location with environment variable for easier deployment
save_dir = os.environ.get("Captures", BASE_DIR)
asi.init('/usr/local/lib/libASICamera2.so')

#Check for rp2040 serial device for servo control
VID = "2e8a"
PID = "000a"
SERIAL = None
MOV_DIR = "O"  # O = further, I = closer
PORT_RP = helper.find_rp2040(VID, PID, SERIAL)
if PORT_RP:
	print(f"Found RP2040 serial device at {PORT_RP} conecting...")
	ser = serial.Serial(PORT_RP, 9600, timeout=1)
	time.sleep(2) # wait for serial connection to establish
	focus = True
else:
	print("No RP2040 serial device found, focus control disabled.")
	focus = False


# Detect whether an X/GUI is available (e.g. via X11 or local display)
display = helper.Gui_Available()
print(f"GUI available: {display}")
# If no DISPLAY in the ssh session, try to detect a local X server and set DISPLAY/XAUTHORITY
if not display:
	if Path("/tmp/.X11-unix/X0").exists():
		os.environ.setdefault("DISPLAY", ":0")
		print("Found local X server: set DISPLAY=':0'")
		# attempt to find an Xauthority file under /home/* or /run/user/*
		xauth_candidates = glob.glob("/home/*/.Xauthority") + glob.glob("/run/user/*/.Xauthority") + glob.glob("/run/user/*/gdm/Xauthority")
		for p in xauth_candidates:
			if Path(p).is_file():
				os.environ.setdefault("XAUTHORITY", p)
				print(f"Using XAUTHORITY={p}")
				break
		# re-evaluate GUI availability
		display = helper.Gui_Available()
		print(f"GUI available after probe: {display}")
		# quick OpenCV window test to see if we can actually open a window
		if display:
			try:
				cv2.namedWindow("test", cv2.WINDOW_NORMAL)
				cv2.imshow("test", np.zeros((2,2,3), dtype=np.uint8))
				cv2.waitKey(1)
				cv2.destroyWindow("test")
			except Exception as e:
				print(f"Warning: OpenCV window test failed: {e}")
				display = False
	if not display:
		print("No GUI detected — preview disabled. To view, enable X11 (ssh -X) or run a VNC server, or use the web preview option.")

cam = helper.connect_camera(retries=10, delay=1)
if not cam:
	exit("No camera Detected. Exiting safely")
helper.monitor_camera(lambda connected: print('Camera connected' if connected else 'Camera removed'))
print("double check", cam)

# print (cam.get_camera_property())

# base cam settings
cam.set_control_value(asi.ASI_BANDWIDTHOVERLOAD, 85)
cam.set_control_value(asi.ASI_HIGH_SPEED_MODE, 1)

# ---- FOCUS PARAMETERS ----
ERROR = 10
metric_diff = ERROR + 1
focus_metric = 0
metric = 0
# ---- AUTO EXPOSURE PARAMETERS ----
w_max, h_max = (1920, 1080)
TARGET_BRIGHTNESS = 100 # 0 to 255
TOLERANCE = 2
SMOOTHING = 0.8


#Preview Parameters
PREVIEW_ROI = (570,320)

# Capture Settings
CAPTURE_ROI = (w_max, h_max)
CAPTURE_EXPOSURE_MAX = 2000000
CAPTURE_GAIN_MAX = 100
CAPTURE_EXPOSURE_MIN = 1000
CAPTURE_GAIN_MIN = 1
# Functions
BAYER_TO_CODE = {
    'BGGR': cv2.COLOR_BayerBG2RGB,
    'RGGB': cv2.COLOR_BayerRG2RGB,
    'GBRG': cv2.COLOR_BayerGB2RGB,
    'GRBG': cv2.COLOR_BayerGR2RGB,
}

def debayer_frame(raw, pattern='RGGB', bit_depth=16, to8bit=True):
    """Return RGB (uint8) image from raw Bayer frame.
    - raw: HxW 1-channel numpy array (uint16 or uint8) or already color HxWx3 array.
    - pattern: one of 'BGGR','RGGB','GBRG','GRBG'.
    - bit_depth: native sensor bits (e.g. 16).
    - to8bit: convert to uint8 (useful for preview).
    """
    if raw is None:
        return None
    # already color -> return a copy
    if getattr(raw, 'ndim', 0) == 3 and raw.shape[2] >= 3:
        return raw.copy()
    arr = raw
    # if 16-bit and want 8-bit, downscale fast:
    if to8bit and arr.dtype == np.uint16:
        shift = max(0, bit_depth - 8)
        arr8 = (arr >> shift).astype(np.uint8)
    elif to8bit and arr.dtype != np.uint8:
        # fallback safe scaling
        arr8 = (arr.astype(np.float32) / max(arr.max(), 1) * 255.0).astype(np.uint8)
    else:
        arr8 = arr

    code = BAYER_TO_CODE.get(pattern.upper(), cv2.COLOR_BayerBG2RGB)
    rgb = cv2.cvtColor(arr8, code)  # returns HxWx3 (RGB)
    return rgb

def focus_metric_laplacian(frame, previous_metric=0):
	"""Compute focus metric (Laplacian variance) robustly for 1- or 3-channel frames."""
	if frame is None:
		return 0.0
	# Handle color or single-channel images
	focus_area = cv2.resize(frame, (100, 100), interpolation=cv2.INTER_AREA)
	if getattr(focus_area, "ndim", None) == 3:
		ch = focus_area.shape[2]
		if ch == 4:
			# drop alpha
			focus_area = cv2.cvtColor(focus_area, cv2.COLOR_RGBA2RGB)
			grey = cv2.cvtColor(focus_area, cv2.COLOR_RGB2GRAY)
		elif ch == 3:
			grey = cv2.cvtColor(focus_area, cv2.COLOR_RGB2GRAY)
		else:
			# unexpected channel count; use first channel
			grey = focus_area[:, :, 0]
	else:
		grey = focus_area
	# Convert to uint8 if necessary
	if grey.dtype != np.uint8:
		maxv = grey.max() if grey.size else 1
		if maxv > 255:
			grey = (grey / (maxv / 255)).astype(np.uint8)
		else:
			grey = grey.astype(np.uint8)
	new_metric = cv2.Laplacian(grey, cv2.CV_64F).var()
	smoothed_metric = 0.8 * previous_metric + 0.2 * new_metric
	return smoothed_metric

def normalize_to_8bit(arr, bit_depth=16, black_level=0, white_level=None, method='percentile', percentile=99.5):
    """Return uint8 image scaled from a 1-channel 16-bit (or other) array."""
    if arr is None:
        return None
    a = arr.astype(np.float32) - float(black_level)
    a[a < 0] = 0.0

    if method == 'bitshift':
        # fastest: assumes full range [0, 2^bit_depth-1] and zero black level
        shift = max(0, bit_depth - 8)
        return (arr >> shift).astype(np.uint8)

    # determine top scale (white level)
    if white_level is None:
        white = np.percentile(a, percentile) if method == 'percentile' else a.max() if a.size else 1.0
    else:
        white = float(white_level)
    white = max(white, 1.0)

    out = (a / white * 255.0)
    out = np.clip(out, 0, 255).astype(np.uint8)
    return out

def measure_brightness(frame):
	"""Return mean brightness robustly for different frame shapes/dtypes."""
	norm8 = normalize_to_8bit(frame, bit_depth=16, method='bitshift', percentile=99.5)
	repROI = cv2.resize(norm8, (100, 100), interpolation=cv2.INTER_AREA)

	if repROI is None:
		return 0.0
	if getattr(repROI, "ndim", None) == 3:
		ch = repROI.shape[2]
		if ch in (3, 4):
			grey = cv2.cvtColor(repROI, cv2.COLOR_RGB2GRAY)
		else:
			grey = repROI[:, :, 0]
	else:
		grey = repROI
	# ensure numeric type
	if grey.dtype != np.uint8:
		maxv = grey.max() if grey.size else 1
		if maxv > 255:
			grey = (grey / (maxv / 255)).astype(np.uint8)
		else:
			grey = grey.astype(np.uint8)
	return np.median(grey)

def auto_adjust_exposure(cam, prev_brightness, exposure, gain, exposure_max, exposure_min, gain_max, gain_min, SMOOTHING, previous_metric):
	frame = cam.capture_video_frame()
	brightness = measure_brightness(frame)
	focus_metric = focus_metric_laplacian(frame, previous_metric)

	exposure_error = float(brightness - TARGET_BRIGHTNESS)
	SMOOTHING = max(0.1, min(0.99, (abs(exposure_error) + 1) ** (-abs(exposure_error)/1000)))
	smoothed = SMOOTHING * prev_brightness + (1- SMOOTHING) * brightness

	if abs(exposure_error) > 2:
		if exposure_error < 0:
			if exposure_min <= exposure < exposure_max:
				exposure *= 1.01 + (0.99 - SMOOTHING)
			elif exposure >= exposure_max:
				gain *=  1.01 + (0.99 - SMOOTHING) if gain < gain_max else gain_max
		elif exposure_error > 0:
			if (exposure > exposure_min) and (gain > gain_min):
				gain = max(gain - 1 - (0.99 - SMOOTHING), 0)
			elif exposure > exposure_min:
				exposure *= 0.99 - (0.99 - SMOOTHING) 
				
	exposure = exposure_max if exposure > exposure_max else exposure
	gain = gain_max if gain > gain_max else gain
	exposure = exposure_min if exposure < exposure_min else exposure
	gain = gain_min if gain < gain_min else gain
	cam.set_control_value(asi.ASI_EXPOSURE, int(exposure))
	cam.set_control_value(asi.ASI_GAIN, int(gain))
	
	print(f"Brightness: {brightness:.1f} ERROR: {exposure_error:.1f} SMOOTHING {SMOOTHING:.2f} smoothed {smoothed:.2f} Exposure: {int(exposure)} Gain: {int(gain)} Focus Metric: {focus_metric:.2f}")
	return smoothed, exposure, gain, SMOOTHING, focus_metric, frame

def setup_mode(cam):
	w, h = CAPTURE_ROI
	start_x = (w_max - w) // 2
	start_y = (h_max - h) // 2
	cam.set_roi(start_x,start_y, w, h)
	cam.set_roi_format(w, h, 1, asi.ASI_IMG_RAW16)
	cam.set_control_value(asi.ASI_EXPOSURE, 50000)
	cam.set_control_value(asi.ASI_GAIN, 1)
	# start the capture stream so capture_video_frame() delivers frames
	cam.start_video_capture()

	return CAPTURE_EXPOSURE_MAX, CAPTURE_EXPOSURE_MIN, CAPTURE_GAIN_MAX, CAPTURE_GAIN_MIN, asi.ASI_IMG_RAW16

def auto_adjust_focus(cam, metric):
	global MOV_DIR, ser
	frame = cam.capture_video_frame()
	new_metric = focus_metric_laplacian(frame)
	brightness = measure_brightness(frame)
	# compute metric difference safely (metric may be empty)
	if metric:
		metric_diff = new_metric - metric
	else:
		metric_diff = 0.0

	if metric_diff > 0:
		print(f"Focus improving: {new_metric:.2f} (+{metric_diff:.2f})")
		if focus and 'ser' in globals() and ser:
			try:
				cmd = f"{int(abs(metric))}{MOV_DIR}\n".encode('utf-8')
				ser.write(cmd)
			except Exception as e:
				print(f"Warning: failed to write serial command: {e}")
	elif metric_diff < 0:
		MOV_DIR = "I" if MOV_DIR == "O" else "O"
		print(f"Reversing movement direction to {MOV_DIR}")
		if focus and 'ser' in globals() and ser:
			try:
				cmd = f"{int(abs(metric))}{MOV_DIR}\n".encode('utf-8')
				ser.write(cmd)
			except Exception as e:
				print(f"Warning: failed to write serial command: {e}")

	print (f"METRIC_DIFF: {metric_diff}, MOV_DIR: {MOV_DIR}")
	metric = new_metric
	return frame, metric, brightness

def post(frame):
	rgb = debayer_frame(frame, pattern='RGGB', bit_depth=16, to8bit=True)
	colour_frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
	preview_frame = cv2.resize(colour_frame, PREVIEW_ROI, interpolation=cv2.INTER_AREA)
	cv2.imshow('ASI662MC', preview_frame)
	return

def save_capture(frame, BASE_DIR, save_dir):
	print("Capture command received on stdin, saving frame...")
	ts = int(time.time())
	base = f"capture_{ts}"
	try:
		filename = f"{base}.tiff"
		print(f"TIFF file made: {filename}")
	except Exception:
		filename = f"{base}.npy"
		print(f"NPY file made: {filename}")
	except Exception as e:
		print(f"Failed to save capture: {e}")
		save = None
		return None
	save = True
	if save is not None:
		try:
			if not os.path.exists(save_dir):
				try:
					os.makedirs(save_dir, exist_ok=True)
					print(f"Created save directory: {save_dir}")
				except Exception as e:
					print(f"Failed to create save directory {save_dir}: {e}")
					return None
			path = os.path.join(save_dir, filename)
			if filename.endswith('.tiff') and TIFF_AVAILABLE:
				# If frame is single-channel (raw Bayer) debayer to RGB so TIFF opens as color in editors
				save_frame = frame
				if getattr(frame, 'ndim', 0) == 2 or (getattr(frame, 'ndim', 0) == 3 and frame.shape[2] == 1):
					try:
						# Use full bit depth debayer (do not convert to 8-bit)
						save_frame = debayer_frame(frame, pattern='RGGB', bit_depth=16, to8bit=False)
					except Exception as e:
						print(f"Warning: debayer failed, saving raw frame: {e}")
				# If multi-channel, ensure we write as RGB photometric for compatibility with Photoshop
				if getattr(save_frame, 'ndim', 0) == 3 and save_frame.shape[2] >= 3:
					tifffile.imwrite(path, save_frame, photometric='rgb', planarconfig='contig')
				else:
					tifffile.imwrite(path, save_frame)
				print(f"Saved TIFF: {path}")
			else:
				np.save(path, frame)
				print(f"Saved NPY: {path}")
		except Exception as e:
			print(f"Failed to save capture to {save_dir}: {e}")
			return None
	return None
	
#---- MAIN LOOP ----
i = 0
# allow graceful exit via signals and shell stdin
running = True
def handle_signal(signum):
	global running
	print(f"Received signal {signum}, shutting down...")
	running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

try:
	# Use capture mode for continuous high-res stream; preview is downscaled below
	exposure_max, exposure_min, gain_max, gain_min, img_type = setup_mode(cam)
	exposure = cam.get_control_value(asi.ASI_EXPOSURE)[0]
	gain = cam.get_control_value(asi.ASI_GAIN)[0]
	brightness = 0

	# Create a borderless fullscreen preview window on the attached screen
	if display:
		try:
			preview_w, preview_h = PREVIEW_ROI
			cv2.namedWindow('ASI662MC', cv2.WINDOW_NORMAL)
			# set window to the preview resolution then request fullscreen
			cv2.resizeWindow('ASI662MC', preview_w, preview_h)
			cv2.moveWindow('ASI662MC', 0, 0)
			cv2.setWindowProperty('ASI662MC', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
			print(f"Preview window created fullscreen at {preview_w}x{preview_h}")
		except Exception as e:
			print(f"Warning: could not create fullscreen preview window: {e}")
	
	while running:
		bright_diff = abs(brightness - TARGET_BRIGHTNESS)
		if bright_diff > TOLERANCE:
			print("Auto exposure mode")
			brightness, exposure, gain, SMOOTHING, previous_metric, frame = auto_adjust_exposure(
				cam, brightness, exposure, gain,
				exposure_max, exposure_min, gain_max, gain_min, SMOOTHING, previous_metric)
		else:
			print("Auto focus mode")
			frame, metric, brightness = auto_adjust_focus(cam, metric)
		post(frame)
		key = cv2.waitKey(1)
		
			
		# GUI quit key
		if key == ord('q'):
			print("GUI requested quit")
			running = False
			break
		# Shell stdin non-blocking quit (type 'q' + Enter in the shell)
		try:
			# add diagnostics so we can see whether stdin is available and usable
			if sys.stdin:
				try:
					iat = sys.stdin.isatty()
				except Exception as e_iat:
					iat = f"error: {e_iat}"
				if (i == 0):
					print(f"stdin present; isatty={iat}")
					i = 1
				# try select regardless of isatty (but capture any select errors)
				try:
					r,_,_ = select.select([sys.stdin], [], [], 0)
				except Exception as e_sel:
					print(f"select on stdin failed: {e_sel}")
					r = []
				if r:
					try:
						fd = sys.stdin.fileno()
						data = os.read(fd, 4096)
						if isinstance(data, bytes):
							cmd = data.decode('utf-8', errors='ignore').strip()
						else:
							cmd = str(data).strip()
					except Exception as e_read:
						print(f"Error reading stdin: {e_read}")
						try:
							cmd = sys.stdin.readline().strip()
						except Exception as e_rl:
							print(f"Error readline fallback: {e_rl}")
							cmd = ''
					print(f"stdin cmd: {cmd!r}")
					cmd_l = cmd.lower()
					if cmd_l in ('q', 'quit', 'exit'):
						print("Quit command received on stdin, exiting...")
						running = False
						break
					elif cmd_l in ('s', 'c', 'capture'):
						save_capture(frame, BASE_DIR, save_dir)

		except Exception as e:
			print(f"stdin handler error: {e}")
				
		time.sleep(0.05)

except KeyboardInterrupt:
	print("Stopping Capture...")
except serial.SerialException as e:
	print(f"ERROR opening serial port {e}. Exiting...")

finally:
	cam.stop_video_capture()
	if display:
		cv2.destroyWindow('ASI662MC')

