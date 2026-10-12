cmake_minimum_required(VERSION 3.16)
project(weave_world LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_subdirectory(engine)
add_subdirectory(game)
add_subdirectory(tools)
enable_testing()
add_subdirectory(tests)
