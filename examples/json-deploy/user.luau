-- A small user program for the json-deploy example. Smaller than the
-- split-deploy version so the predecoded user AST stays readable.

print(`hello from {hostInfo.appName} v{hostInfo.appVersion}`)

-- closures + upvalues
local function makeCounter()
    local n = 0
    return function() n += 1; return n end
end

local c = makeCounter()
print(`counter: {c()}, {c()}, {c()}`)

-- a small table-driven loop
local prices = {apple = 0.5, banana = 0.25, cherry = 1.1}
local total = 0
for name, p in pairs(prices) do
    total += p
end
print(`basket total: {total}`)

-- metatable
local Vec = {}
Vec.__index = Vec
function Vec.new(x, y) return setmetatable({x = x, y = y}, Vec) end
function Vec.__add(a, b) return Vec.new(a.x + b.x, a.y + b.y) end
function Vec.__tostring(v) return `Vec({v.x},{v.y})` end

local v = Vec.new(3, 4) + Vec.new(1, 2)
print(`v = {v}`)

-- pcall + assert
local ok, err = pcall(function() assert(false, "intentional") end)
print(`pcall returned ok={ok} err={err}`)

print("user.luau done")
