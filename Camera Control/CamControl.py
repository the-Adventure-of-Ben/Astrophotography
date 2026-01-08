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


# ---- SET UP ----
BASE_DIR = "/home/sauron/astro/"
save_dir = BASE_DIR
asi.init('/usr/local/lib/libASICamera2.so')

#Check for rp2040 serial device for servo control
VID = "2e8a"
PID = "000a"
SERIAL = None
PORT_RP = helper.find_rp2040(VID, PID, SERIAL)


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



# ---- AUTO EXPOSURE PARAMETERS ----
w_max, h_max = (1920, 1080)
TARGET_BRIGHTNESS = 100 # 0 to 255
TOLERANCE = 1
SMOOTHING = 0.8


#Preview Parameters
PREVIEW_ROI = (480,320)
PREVIEW_EXPOSURE_MAX = 10000
PREVIEW_GAIN_MAX = 300

# Capture Settings
CAPTURE_ROI = (w_max, h_max)
CAPTURE_EXPOSURE_MAX = 2000000
CAPTURE_GAIN_MAX = 400
POS = []
METRIC = []
# Functions
def focus_metric_laplacian(frame):
	grey = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
	return float(cv2.Laplacian(grey, cv2.CV_64F).var())
def measure_brightness(frame):
	grey = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
	return np.mean(grey)

def auto_adjust(cam, prev_brightness, exposure, gain, exposure_max, gain_max, SMOOTHING, pos):
	frame = cam.capture_video_frame( )
	frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
	brightness = measure_brightness(frame)
	metric = focus_metric_laplacian(frame)
	METRIC.append(metric)
	pos.append(POS)

	error = float(brightness - TARGET_BRIGHTNESS)
	SMOOTHING = max(0.1, min(0.99, (abs(error) + 1) ** (-abs(error)/1000)))
	smoothed = SMOOTHING * prev_brightness + (1- SMOOTHING) * brightness
	
	
	if abs(error) > TOLERANCE:
		if error < 0:
			if 1000 <= exposure < exposure_max:
				exposure *= 1.01 + (0.99 - SMOOTHING)
			elif exposure >= exposure_max:
				gain = min(gain + 1 + (0.99 - SMOOTHING), gain_max)
			elif exposure < 1000:
				exposure = 1000
		else:
			if (exposure > 1000) and (gain > 0):
				gain = max(gain - 1 - (0.99 - SMOOTHING), 0)
			elif exposure > 1000:
				exposure *= 0.99 - (0.99 - SMOOTHING) 
				
	cam.set_control_value(asi.ASI_EXPOSURE, int(exposure))
	cam.set_control_value(asi.ASI_GAIN, int(gain))
	
	#print(f" Brightness: {brightness:.1f} ERROR: {error:.1f} SMOOTHING {SMOOTHING:.2f} smoothed {smoothed:.2f} Exposure: {int(exposure)} Gain: {int(gain)}")
	return smoothed, exposure, gain, SMOOTHING, frame

def setup_mode(cam):
	w, h = CAPTURE_ROI
	start_x = (w_max - w) // 2
	start_y = (h_max - h) // 2
	cam.set_roi(start_x,start_y, w, h)
	cam.set_roi_format(w, h, 1, asi.ASI_IMG_RAW16)
	cam.set_control_value(asi.ASI_EXPOSURE, 50000)
	cam.set_control_value(asi.ASI_GAIN, 0)
	# start the capture stream so capture_video_frame() delivers frames
	cam.start_video_capture()

	return CAPTURE_EXPOSURE_MAX, CAPTURE_GAIN_MAX, asi.ASI_IMG_RAW16	 

#---- MAIN LOOP ----

# allow graceful exit via signals and shell stdin
running = True
def handle_signal(signum, frame):
	global running
	print(f"Received signal {signum}, shutting down...")
	running = False

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

try:
	# Use capture mode for continuous high-res stream; preview is downscaled below
	exposure_max, gain_max, img_type = setup_mode(cam)
	exposure = cam.get_control_value(asi.ASI_EXPOSURE)[0]
	gain = cam.get_control_value(asi.ASI_GAIN)[0]
	brightness = TARGET_BRIGHTNESS

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
		brightness, exposure, gain, SMOOTHING, frame = auto_adjust(
			 cam, brightness, exposure, gain,
			 exposure_max, gain_max, SMOOTHING, img_type
		 )
		# Downscale full-resolution frame for a low-res preview (Option B)
		preview_w, preview_h = PREVIEW_ROI
		preview_frame = cv2.resize(frame, (preview_w, preview_h), interpolation=cv2.INTER_AREA)
		# Only try to show a window if a GUI/display is actually available
		if display:
			cv2.imshow('ASI662MC', preview_frame)
			key = cv2.waitKey(1)
		else:
			key = -1
		# GUI quit key
		if key == ord('q'):
			print("GUI requested quit")
			running = False
			break
		# Shell stdin non-blocking quit (type 'q' + Enter in the shell)
		try:
			if sys.stdin and sys.stdin.isatty():
				r,_,_ = select.select([sys.stdin], [], [], 0)
				if r:
					cmd = sys.stdin.readline().strip()
					if cmd in ('q', 'quit', 'exit'):
						print("Quit command received on stdin, exiting...")
						running = False
						break
					elif cmd in ('s', 'c', 'capture' ):
						filename = f"capture_{int(time.time())}.png"
						path = os.path.join(save_dir, filename)
						cv2.imwrite(filename, frame)
						print("Saved", filename)
		except Exception:
			pass
		# elif key == ord('s'):
		# 	filename = f"capture_{int(time.time())}.png"
		# 	path = os.path.join(save_dir, filename)
		# 	cv2.imwrite(filename, frame)
		# 	print("Saved", filename)		
		
		time.sleep(0.05)

except KeyboardInterrupt:
	print("Stopping Capture...")

finally:
	cam.stop_video_capture()
	if display:
		cv2.destroyWindow('ASI662MC')

