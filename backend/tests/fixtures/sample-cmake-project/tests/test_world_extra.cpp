#include "engine/World.hpp"

#include <cassert>
#include <iostream>

int main() {
    engine::World world;
    world.add("extra");
    assert(world.greet("extra") == "hello extra");
    std::cout << "test_world_extra ok\n";
    return 0;
}
