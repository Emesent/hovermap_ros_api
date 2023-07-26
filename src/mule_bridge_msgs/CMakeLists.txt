cmake_minimum_required(VERSION 3.5.1)

project(mule_bridge_msgs)

find_package(catkin REQUIRED COMPONENTS
  message_generation
)

add_message_files(FILES
  LogIndex.msg
  Manifest.msg
  Peer.msg
  Status.msg
  Topic.msg
)

add_service_files(FILES
  SetOverlay.srv
)

generate_messages()

catkin_package(CATKIN_DEPENDS
  message_runtime
)
