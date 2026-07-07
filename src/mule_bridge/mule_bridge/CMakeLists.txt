cmake_minimum_required(VERSION 3.16)

project(mule_bridge)

set(${PROJECT_NAME}_VERSION "1.0.0")

find_package(catkin REQUIRED COMPONENTS)

catkin_python_setup()

catkin_package()

catkin_install_python(PROGRAMS scripts/mule_bridge DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION})

if(CATKIN_ENABLE_TESTING)

  SET(PYTHON_TEST_TARGETS
    tests/test_database.py
    tests/test_history.py
    tests/test_protocol.py
  )

  foreach(TEST_TARGET ${PYTHON_TEST_TARGETS})
    catkin_add_nosetests(${TEST_TARGET})
  endforeach()

  find_package(rostest REQUIRED)
  add_rostest(tests/test_bridge.test)
endif()
