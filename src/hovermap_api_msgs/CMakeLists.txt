cmake_minimum_required(VERSION 3.16)
project(hovermap_api_msgs)

find_package(catkin REQUIRED COMPONENTS
  message_generation
  std_msgs
)

add_message_files(FILES
  ScanInformation.msg
  ScanInformationList.msg
  HovermapStatus.msg
)

generate_messages(
  DEPENDENCIES
  std_msgs
)

catkin_package(
  CATKIN_DEPENDS
  message_runtime
  std_msgs
)
