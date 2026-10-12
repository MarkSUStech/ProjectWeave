#include "engine/World.hpp"

#include <iostream>

int main(int argc, char** argv) {
    engine::World world;
    world.add("probe");
    const int count = argc > 1 ? std::atoi(argv[1]) : 1;
    for (int i = 0; i < count; ++i) {
        std::cout << world.greet("probe") << "\n";
    }
    return 0;
}
