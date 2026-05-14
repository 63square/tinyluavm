-- Metatables for operator overloading and class-like patterns.
local Vec = {}
Vec.__index = Vec
Vec.__add = function(a, b) return Vec.new(a.x + b.x, a.y + b.y) end
Vec.__tostring = function(v) return `Vec({v.x}, {v.y})` end

function Vec.new(x: number, y: number)
    return setmetatable({x = x, y = y}, Vec)
end

function Vec:length()
    return math.sqrt(self.x * self.x + self.y * self.y)
end

local a = Vec.new(3, 4)
local b = Vec.new(1, 2)
local c = a + b
print(tostring(a), "+", tostring(b), "=", tostring(c))
print("|a| =", a:length())
