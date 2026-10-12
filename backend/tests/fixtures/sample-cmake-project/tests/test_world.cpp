#include "engine/World.hpp"

#include <cassert>
#include <iostream>

int main() {
    engine::World world;
    world.add("weave");
    assert(world.greet("weave") == "hello weave");
    assert(world.greet("nobody") == "unknown nobody");
    assert(world.size() == 1);
    std::cout << "test_world ok\n";
    return 0;
}
