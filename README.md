# Astrophotography
### !Currenlty in development!

**_DISCLAMER: currently a lot of the code is writen by AI. This is due to my lack of understanding with the programing languages and libraries. Of course I use my brain and try to figure things out first and stitch thing together._**

**Help would be appreciated, please message in the dicussion to become a collaborator**

Very specilised to my need currently so that I can test the software with the hardware, though it will be generalised so that others can use it more easily.

  
This is a project that should allow for full control of a telescope that doesn't have an automatic tracker as they are expensive. The system is split into three main subsystems _telescope control_, _camera system_ and _communication subsystem_.  

<details>
  
<summary>Current system parts:</summary>

**Current telescope control system parts:**
- Two stepper motors (one for azimuth, other for altitude).
- Arduino mega to control the stepper motors.
- A TMC2209 chip for each stepper motor.
- A Bluetooth chip for communiaction with an android phone (Apple doesn't like it).
- A mag compass to check orientaion of the telescope
- A battery to power this system

**Current camera system parts:**
- ZWO ASI662MC
- Rasperry Pi 5 with 8gb of RAM
- M.2 HAT with a 512 GB SSD
- YAHBOOM Raspberry Pi power supply expansion board
- LCD srceen
- RP2040-zero
- FS90R continuous servo
- Battery

**Current comunication system parts:**
- Android phone
- home computer
- Heltec LoRa v4
- Heltec LoRa v3
- Meshtastic

</details>

<details open>
<summary>System explantions:</summary>
  <br/>
This section goes through how the system works as well as how future additions should/might work, all of which is subject to change.
  <br/> <br/>
The first subsystem to talk about is the Telescope control (TC). TC is used to point the telescope at a certain part of the sky, so that a photo/s can be taken of it. To achieve this two stepper motors are used, one move about the azimuth and the other the altitude which is a fairly common setup for auto telescopes. The steppers positon is controlled by an Ardiuno mega which itself recives the values from the android phone via bluetooth. The application to do this has yet to be completed. 
<br/> <br/>
The second subsystem is the Camera Control (CC). The CC primary funtion is to capture clear high quality photos through the telescope, this why an astrophotography camera is used in conjunction with a Raspberry Pi. To get clear high quality photos the exposure, gain and focus of the camera need to be controled, with the focus as sharp as possible and the exposure to gain ratio balanced. Exposure is the amount of time that the sensor takes in light, the longer the exposure the brighter the image, though too long of an exposure results in image bluring due to the subject moving through frame. Gain reduces the exposure time by internally increasing the brightness values of the whole image, which results in a brighter image with less exposure time so the image doesn't blur, though the higher the gain the more noisy the image becomes. So a balance between exposure time and gain levels is need so that a blur free and noise free image is produced. The focusing and exposure gain balancing is handeled by the Pi (though this needs tuning as it hasn't been tested). While exposure time and gain are comands sent to camera, focusing the camera isn't as the camera has no lense, instead a continuous servo is used to turn the focus on the telescope itself. This done through a RP2040-zero due to the pins on the Pi 5 being taken by the M.2 HAT. The Pi 5 will communicate to the RP2040 via usb and it will handle the PWM and possibly position calculations. This need to be implemented and tested. The Pi 5 will alsp use a small LCD screen to preview what the telescope is seeing, just so you know if it is pointing at what you want it to, though this isn't necessary to the functions of the camera. In addition to capturing an image, the Pi 5 will also be able to finalize the image, most likely through Sigril.<br/>
It should also be mentiond that the Pi 5 need to be SSHed into to run the programe/s and to control it. This should be possble through a phone, and due to its use with a phone the comands will be kept short.
<br/><br/>
The third subsytem, though currently underdeveloped, is the communication subsystem (CS). The CS is what meshes the subsystems together, some thought has been put into it but not enough. The current requirments of the system is to get the gps location, magnetic declination, azimuth and altitude of the subject. The latter 3 require internet connection to accurately assertain as they come from APIs and would be difficult to calcualte otherwise. This would mean that CS would fail outside cell service, to fix this a Meshtastic node will be set up in or near the telescope (the former if it has gps) and another will be connected to internet somewhere else. This means that the needed values can be requested through the node, potentialy using other nodes to reach eachother. One problem with this method is that it is slow with latency mesured in seconds rather than milliseconds and can't be used to stream data quickly. However the data that is being requsted is needed once every 3 seconds (this is to track the moon), and Meshtastic is capable of doing this.
<br/><br/>
Finaly, somethings for future implementaion. The biggest is to complete my very specific use case to make sure what I am doing is possible, then for it to be made more accessble by generalising the code. To do this the control application would need to be made, then the focus function and then the Meshtastic implementation. the Meshtastic is the least important in this phase of the project as taking the system out of cell service is the last thing I will do a check that the whole system is complete to a minimum.

</details>

## Todo lists:

**Important:**
- [ ] implement the focusing function
- [ ] Build the Application for the phone
- [ ] Meshtastic implementation 

**Not As Important:**
- [ ] add image prossessing

## This Project uses the GPL-3.0 licence to keep it open source.  
[See LICENCE DOC](LICENSE) for the rules.
