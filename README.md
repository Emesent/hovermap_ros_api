# Hovermap ROS API

ROS 1 meta-package to get access to the Hovermap online data through a client computer.

## Pre-requisites

The Hovermap API setup requires:

- an Emesent Hovermap
- a client computer running Ubuntu 20.04 LTS with ROS 1 Noetic installed
- an Emesent Hovermap connected to the client computer with a Hovermap ST Fischer-to-Ethernet interface; or a USB-to-Ethernet adaptor

## Quick Start

### 1. Install dependencies

1. Install ROS noetic: <http://wiki.ros.org/noetic/Installation/Ubuntu>
2. Install project dependencies and clone the project

```bash
sudo apt update
sudo apt install chrony python3-catkin-tools -y
mkdir -p hovermap_ros_api/src
cd hovermap_ros_api/src
git clone git@github.com:Emesent/hovermap_ros_api.git
rosdep install --from-paths src --ignore-src --rosdistro=${ROS_DISTRO} -y
python3 -m pip install -r mule_bridge/requirements.txt
```

### 2. Enable the Hovermap API

1. Power on Hovermap
2. Connect to Hovermap via the WiFi access point; SSID named after the Hovermap serial number (e.g. `st_0001`)
3. Enable the external API through the Hovermap Web UI
    1. Visit <http://hover.map> on a web browser
    2. Switch on the "Publish external API messages" option

    <img src="/doc/images/webui_switch.png" width="450" />

    **Note**: if the option does not appear you will need to contact Emesent about an updated entitlement file.
4. Power cycle Hovermap and verify the external API is enabled.

### 3. Connect to the Hovermap

The API is configured to connect over Ethernet on boot time with one of the following interfaces with their specific configurations:

| Interface                 | ip_prefix   | Hovermap address | Client address   | Netmask       |
|---------------------------|-------------|------------------|------------------|---------------|
| ST Fischer-to-Ethernet    | 192.168.2.0 | 192.168.2.115    | 192.168.2.100    | 255.255.255.0 |
| USB-to-Ethernet           | 192.168.3.0 | 192.168.3.115    | 192.168.3.100    | 255.255.255.0 |

1. Plug in the physical connection from your machine to the Hovermap over
your desired interface
2. Set up a network profile with a manual static IP as specified in the "Client address" from the table

<img src="/doc/images/eth_profile.png" width="450" />

3. Check the Ethernet connection is setup correctly by pinging Hovermap

```bash
ping -c 5 192.168.2.115 # Hovermap address as specified in table above
```

4. Edit the [mule.yaml](hovermap_api/config/mule.yaml) config file to fill out these values for your network interface with your ethernet connection.

```yaml
mule_network: "enxc03ebad2cd9c" # Your active network interface name with IP 192.168.2.100 
ip_prefix: "192.168.2.0"        # as in the table
ip_netmask: "255.255.255.0"     # as in the table
```

5. Build and launch the Hovermap API

```bash
catkin build hovermap_api
source <path_to_workspace>/install/setup.bash
roslaunch hovermap_api api.launch
```

6. Verify the API connection works successfully by checking the rosout and getting this message:

```yaml
started core service [/rosout]
process[hovermap_api_mule-2]: started with pid [239]
[INFO] [1689641473.095754]: Delay started (give subscribers time to connect)
[INFO] [1689209676.101692]: Delay finished
[INFO] [1689209676.609904, 2930.950000]: Added peer st_0001 at tcp://192.168.2.115:{49184,49189}
[INFO] [1689209676.613040, 2930.959000]: Connected to st_0001 at tcp://192.168.2.115:49189
```

``` bash
$ rostopic list
/hovermap_api_mule/status
/odometry
/pointcloud
/rosout
/rosout_agg
/tf
/tf_static
```

7. Start a Mapping mission either on the Web UI or through Commander

## API ROS topics

| Topic name                | Type                   | Description                      | Update Rate (Hz)  | Notes |
|---------------------------|------------------------|----------------------------------|-------------------|-------|
| /hovermap_api_mule/status | mule_bridge_msgs/Status| Internal mule status             | 1                 |
| /tf_static                | tf_msgs/TFMessage      | Static transforms                | Once (latched)    | |
| /tf                       | tf_msgs/TFMessage      | Non-static transform             | Variable          | |
| /odometry                 | nav_msgs/Odometry      | SLAM corrected odometry          | 100               | |
| /pointcloud               | sensor_msgs/PointCloud2| Occupancy grid for navigation    | 1                 | 256x256x256 grid; 0.25m resolution |

### Topic details

1. Transform tree (tf and tf_static)
    - The TF contains the depicted below
    - It follows [REP 105](https://www.ros.org/reps/rep-0105.html) convention
    - `hovermap_base` is the external reference point on hovermap and it is located as depicted below
    - `hovermap_base` and `base_link` are coincident when hovermap is attached to an unsupported robotic platform
    - `base_link` referenced the robot reference axis for navigation and control purposes when attached to a supported robotic platform

Tf tree             |  Reference axis
:-------------------------:|:-------------------------:
<img src="/doc/images/tf_tree.png" width="450" /> | <img src="/doc/images/st_reference_axis.png" width="450" />


2. Odometry (/odometry)
    - Local SLAM corrected odometry from `odom` to `hovermap_base`
    - If global (mission) corrected odometry is required the `map->odom` transform should be applied to the `odometry` value
    - Topic covariance is not populated

3. Occupancy grid (/pointcloud)
    - Fixed size 3D occupancy grid describing local obstacles detected by the Hovermap
    - It is meant to be used for navigation purposes only

## Time Synchronisation

The Hovermap is configured to act as an NTP server to allow API users synchronise the client's clock to the Hovermap's by:

1. Synchronise the client with the Hovermap by editing `/etc/chrony/chrony.conf`
    - add `server 192.168.2.115  iburst`
    - remove/comment any other `server` or `pool` directives the file
2. Start chrony as a service with `service chrony start`
3. Check the offset between the clocks with `chronyc tracking`

```
Reference ID    : C0A80273 (192.168.2.115)
Stratum         : 11
Ref time (UTC)  : Wed Jul 12 05:49:04 2023
System time     : 0.000000002 seconds slow of NTP time
Last offset     : +0.000003220 seconds
RMS offset      : 0.000048081 seconds
Frequency       : 3.325 ppm slow
Residual freq   : +0.001 ppm
Skew            : 0.801 ppm
Root delay      : 0.000319398 seconds
Root dispersion : 0.002432903 seconds
Update interval : 64.0 seconds
Leap status     : Normal
```

**Note** : Chrony synchronises clocks by slowly skewing towards the target clock. Consequently a large offset between
clocks may take a while to converge. In this case, run `sudo chronyc -a makestep` to force chrony to discontinuously change the time to the server time.
