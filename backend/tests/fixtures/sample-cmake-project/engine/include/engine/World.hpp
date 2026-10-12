#pragma once

#include <string>
#include <vector>

namespace engine {

// 世界：注册实体并生成问候/地形数据（教学用确定性实现）。
class World {
public:
    void add(const std::string& name);
    std::string greet(const std::string& name) const;

    // 地形高程（确定性分段函数：x<0 → 5，否则 10）
    double terrain_elevation(double x) const;

    std::size_t size() const { return entities_.size(); }

private:
    std::vector<std::string> entities_;
};

}  // namespace engine
