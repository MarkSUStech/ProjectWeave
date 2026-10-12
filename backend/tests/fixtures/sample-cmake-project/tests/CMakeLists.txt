add_executable(test_world test_world.cpp)
target_link_libraries(test_world PRIVATE engine)
add_test(NAME test_world COMMAND test_world)

add_executable(test_terrain test_terrain.cpp)
target_link_libraries(test_terrain PRIVATE engine)
add_test(NAME test_terrain COMMAND test_terrain)

# 前缀碰撞样本（P8.1.1）：ctest -R test_world 不得误匹配 test_world_extra
add_executable(test_world_extra test_world_extra.cpp)
target_link_libraries(test_world_extra PRIVATE engine)
add_test(NAME test_world_extra COMMAND test_world_extra)
