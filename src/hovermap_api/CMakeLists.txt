cmake_minimum_required(VERSION 3.16.3)
project(hovermap_api)

find_package(catkin REQUIRED COMPONENTS
  nav_msgs
  sensor_msgs
  tf2_ros
)

catkin_package(CATKIN_DEPENDS
  nav_msgs
  sensor_msgs
  tf2_ros
)

catkin_install_python(
    PROGRAMS
    scripts/configure_perception
    DESTINATION 
    ${CATKIN_PACKAGE_BIN_DESTINATION})


install(DIRECTORY
    launch
    DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)

install(DIRECTORY
    config
    DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
)

