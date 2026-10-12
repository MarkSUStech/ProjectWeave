#include "engine/World.hpp"

#include <algorithm>

namespace engine {

void World::add(const std::string& name) {
    entities_.push_back(name);
}

std::string World::greet(const std::string& name) const {
    bool known = std::find(entities_.begin(), entities_.end(), name) != entities_.end();
    return known ? "hello " + name : "unknown " + name;
}

double World::terrain_elevation(double x) const {
    return x < 0.0 ? 5.0 : 10.0;
}

}  // namespace engine
