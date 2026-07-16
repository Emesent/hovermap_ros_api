# Use the official ROS Noetic base image
FROM ros:noetic-ros-base

# Set the working directory
WORKDIR /ros_ws

# Use bash as shell
SHELL ["/bin/bash", "-c"]

# Git is not included as the repository is assumed to be cloned on the host.
RUN apt update && apt install -y \
    ros-noetic-catkin \
    ros-noetic-tf2-ros \
    build-essential \
    chrony \
    python3-catkin-tools \
    python3-pip

# Install pip dependencies (only rebuilds if requirements.txt changes)
RUN --mount=type=bind,src=src/mule_bridge/mule_bridge/requirements.txt,dst=/tmp/requirements.txt \
    python3 -m pip install -r /tmp/requirements.txt

# Build the repo into the context
RUN --mount=type=bind,src=src/,dst=/ros_ws/src \
    source /opt/ros/noetic/setup.bash && \
    catkin init && \
    catkin config --install && \
    catkin build

# Launch the hovermap api client
CMD ["/bin/bash", "-c", "source /ros_ws/install/setup.bash && roslaunch hovermap_api api.launch"]
