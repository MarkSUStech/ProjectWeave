#include "engine/World.hpp"

#include <cassert>
#include <iostream>

int main() {
    engine::World world;
    // 故意失败的断言（验收 G：必须显示为 failed，不得判通过）
    assert(world.terrain_elevation(-1.0) == 99.0);
    std::cout << "test_terrain ok\n";
    return 0;
}
