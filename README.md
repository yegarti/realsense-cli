# Realsense-CLI

RealSenseCLI is a command-line utility for interacting with [RealSense](https://github.com/IntelRealSense/librealsense) cameras built on top of [pyrealsense2](https://pypi.org/project/pyrealsense2/).

With this package, you can easily access and control the functionalities of your RealSense cameras directly from the terminal

## Features
- List connected devices info and supported streams
- Configure camera sensor controls
- Stream selected streaming profiles and check for FPS

## Installation
### pipx

Install RealSense-CLI using [pipx](https://pypa.github.io/pipx)
```
pipx install realsense-cli
```

### pip
Install as a regular Python package

```
python -m pip install realsense-cli
```

### Build
Build the package using [Poetry](https://python-poetry.org/)
```
poetry build
```

## Usage

You can call `rs --help` to read the help for every command.

All commands, except `rs list` operate on a single connected device.

In case multiple devices are connected use the `-s/--serial` option to select a device.

### List
List connected devices
```
> rs list
                                       Devices                                       
                                                                                     
          Name              Serial       Firmware    USB Connection      Sensors     
 ─────────────────────────────────────────────────────────────────────────────────── 
  Intel RealSense D435   801312071342   5.13.0.51         2.1         Stereo Module  
                                                                       RGB Camera    
  Intel RealSense D415   732612060537   5.15.0.2         3.2         Stereo Module  
                                                                      RGB Camera   
                                                                                     
```

### Configure

#### List sensor supported controls
```
> rs config list depth

                                                                                         Controls                                                                                           
  Name                     Description                                                                                                        Min Value   Max Value   Step    Default Value  
 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────── 
  exposure                 Depth Exposure (usec)                                                                                              1.0         200000.0    1.0     8500.0         
  gain                     UVC image gain                                                                                                     16.0        248.0       1.0     16.0           
  enable_auto_exposure     Enable Auto Exposure                                                                                               0.0         1.0         1.0     1.0            
  visual_preset            Advanced-Mode Preset                                                                                               0.0         5.0         1.0     0.0            
  laser_power              Manual laser power in mw. applicable only when laser power mode is set to Manual                                   0.0         360.0       30.0    150.0          
  emitter_enabled          Emitter select, 0-disable all emitters, 1-enable laser, 2-enable laser auto (opt), 3-enable LED (opt)              0.0         2.0         1.0     1.0            
  frames_queue_size        Max number of frames you can hold at a given time. Increasing this number will reduce frame drops but increase     0.0         32.0        1.0     16.0           
                           latency, and vice versa                                                                                                                                           
  error_polling_enabled    Enable / disable polling of camera internal errors                                                                 0.0         1.0         1.0     0.0            
  output_trigger_enabled   Generate trigger from the camera to external device once per frame                                                 0.0         1.0         1.0     0.0            
  depth_units              Number of meters represented by a single depth unit                                                                1e-06       0.01        1e-06   0.001          
  inter_cam_sync_mode      Inter-camera synchronization mode: 0:Default, 1:Master, 2:Slave, 3:Full Salve, 4-258:Genlock with burst count of   0.0         260.0       1.0     0.0            
                           1-255 frames for each trigger, 259 and 260 for two frames per trigger with laser ON-OFF and OFF-ON.                                                               
  emitter_on_off           Alternating emitter pattern, toggled on/off on per-frame basis                                                     0.0         1.0         1.0     0.0            
  global_time_enabled      Enable/Disable global timestamp                                                                                    0.0         1.0         1.0     1.0            
  emitter_always_on        Emitter always on mode: 0:disabled(default), 1:enabled                                                             0.0         1.0         1.0     0.0            
  hdr_enabled              HDR Option                                                                                                         0.0         1.0         1.0     0.0            
  sequence_name            HDR Option                                                                                                         0.0         3.0         1.0     1.0            
  sequence_size            HDR Option                                                                                                         2.0         2.0         1.0     2.0            
  sequence_id              HDR Option                                                                                                         0.0         2.0         1.0     0.0            
                                                                                                                                                                                      
```

#### Query sensor controls
```
> rs config depth get exposure laser_power
                        
  Name          Value   
 ────────────────────── 
  exposure      8500.0  
  laser_power   150.0   
                        
```

#### Set sensor controls
```
> rs config set depth exposure=15000 laser_power=120

  Name          Value    
 ─────────────────────── 
  exposure      15000.0  
  laser_power   120.0   
```

### Stream
#### List supported profiles
can be called with a sensor name (`rs stream list depth`) or without sensor to list profiles for all sensors
```
> rs stream list

                     Streams                     
                                                 
  Stream       Resolution   FPS          Format  
 ─────────────────────────────────────────────── 
  Depth        256x144      90           Z16     
  Depth        480x270      6/15/30/60   Z16     
  Depth        640x360      30           Z16     
  Depth        640x480      6/15/30      Z16     
  Depth        848x480      6/8/10       Z16     
  Depth        1280x720     6            Z16     
  Infrared 1   480x270      6/15/30/60   Y8      
  Infrared 1   640x360      30           Y8      
  Infrared 1   640x480      6/15/30      Y8      
  Infrared 1   848x480      6/8/10       Y8      
  Infrared 1   1280x720     6            Y8      
  Infrared 2   480x270      6/15/30/60   Y8      
  Infrared 2   640x360      30           Y8      
  Infrared 2   640x480      6/15/30      Y8      
  Infrared 2   848x480      6/8/10       Y8      
  Infrared 2   1280x720     6            Y8    
  ...
  Color        1280x720     6/10/15      RGB8    
  Color        1280x720     6/10/15      RGBA8   
  Color        1280x720     6/10/15      Y16     
  Color        1280x720     6/10/15      Y8      
  Color        1280x720     6/10/15      YUYV    
  Color        1920x1080    8            BGR8    
  Color        1920x1080    8            BGRA8   
  Color        1920x1080    8            RGB8    
  Color        1920x1080    8            RGBA8   
  Color        1920x1080    8            Y16     
  Color        1920x1080    8            Y8      
  Color        1920x1080    8            YUYV
```

#### Play
Stream profiles and show a live view for incoming frames

- `rs stream play` - Start all streams with default profiles
- `rs stream play depth color infrared2` - Start only given streams with default settings
- `rs stream play depth color --fps 30 --res 1280x720` - Start given streams with 1280x720 resolution at 30 fps

Example for live view (Ctrl-C to exit)
```
> rs stream play
                                                                                                                                                                                             
                                                                                                                                                                                             
  ╭─────── Depth (0) 640x480 15fps z16 ───────╮                                                                                                                                              
  │ Frame #69       FPS: 15.01                │                                                                                                                                              
  ╰───────────────────────────────────────────╯                                                                                                                                              
  ╭───── Infrared 1 (1) 640x480 15fps y8 ─────╮                                                                                                                                              
  │ Frame #66       FPS: 15.01                │                                                                                                                                              
  ╰───────────────────────────────────────────╯                                                                                                                                              
  ╭───── Infrared 2 (2) 640x480 15fps y8 ─────╮                                                                                                                                              
  │ Frame #66       FPS: 15.01                │                                                                                                                                              
  ╰───────────────────────────────────────────╯                                                                                                                                              
  ╭────── Color (0) 640x480 15fps rgb8 ───────╮                                                                                                                                              
  │ Frame #68       FPS: 15.01                │                                                                                                                                              
  ╰───────────────────────────────────────────╯    
```
