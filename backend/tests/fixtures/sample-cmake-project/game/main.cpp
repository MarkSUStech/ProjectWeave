#include "engine/World.hpp"

#include <iostream>

int main() {
    engine::World world;
    world.add("weave");
    std::cout << world.greet("weave") << "\n";
    std::cout << "elevation(-1)=" << world.terrain_elevation(-1.0) << "\n";
    std::cout << "elevation(1)=" << world.terrain_elevation(1.0) << "\n";
    return 0;
}
