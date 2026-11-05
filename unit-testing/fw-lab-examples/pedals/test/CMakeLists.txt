cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# Include shared components from root
set(EXTRA_COMPONENT_DIRS "../../components")

project(pedals_fw_test)
