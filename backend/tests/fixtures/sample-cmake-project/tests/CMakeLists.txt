add_executable(test_world test_world.cpp)
target_link_libraries(test_world PRIVATE engine)
add_test(NAME test_world COMMAND test_world)

add_executable(test_terrain test_terrain.cpp)
target_link_libraries(test_terrain PRIVATE engine)
add_test(NAME test_terrain COMMAND test_terrain)
