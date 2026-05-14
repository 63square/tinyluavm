-- A small but non-trivial Luau program. The launcher compiles this offline
-- and runs it through the tinyvm micro-VM.
--
-- Exercises: closures + upvalues, varargs, multi-return, generic-for over a
-- hash table, numeric-for, string interpolation, compound assignment,
-- a __index/__add metatable, pcall, and access to a host-provided global.

-- The launcher injected `hostInfo` into our env. We can see it like a global.
print(`hello from {hostInfo.appName} v{hostInfo.appVersion}`)

-- -- closures + upvalues -----------------------------------------------------
local function makeCounter(start: number)
    local n = start
    return function()
        n += 1
        return n
    end
end

local nextId = makeCounter(100)
print(`first three ids: {nextId()}, {nextId()}, {nextId()}`)

-- -- varargs + multi-return --------------------------------------------------
local function stats(...): (number, number, number)
    local sum, count = 0, select("#", ...)
    for i = 1, count do
        sum += (select(i, ...))
    end
    return sum, count, sum / count
end

local sum, count, mean = stats(3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5)
print(`stats: sum={sum} count={count} mean={mean}`)

-- -- generic-for over a hash table ------------------------------------------
local prices = {
    apple   = 0.50,
    banana  = 0.25,
    cherry  = 1.10,
    durian  = 7.00,
}
local total = 0
local items = {}
for name, price in pairs(prices) do
    items[#items + 1] = `{name}:{price}`
    total += price
end
-- Sort so the output is stable across pairs() bucket orders.
table.sort(items)
print(`basket: {table.concat(items, ", ")}`)
print(`basket total: {total}`)

-- -- metatable with __add and __index ---------------------------------------
local Vec = {}
Vec.__index = Vec

function Vec.new(x: number, y: number)
    return setmetatable({x = x, y = y}, Vec)
end

function Vec:length(): number
    return math.sqrt(self.x * self.x + self.y * self.y)
end

function Vec.__add(a, b)
    return Vec.new(a.x + b.x, a.y + b.y)
end

function Vec.__tostring(v)
    return `Vec({v.x}, {v.y})`
end

local a, b = Vec.new(3, 4), Vec.new(1, 2)
print(`a = {a}, |a| = {a:length()}`)
print(`a + b = {a + b}`)

-- -- error handling ---------------------------------------------------------
local function safeDiv(x: number, y: number): number
    assert(y ~= 0, "division by zero")
    return x / y
end

local ok, result = pcall(safeDiv, 10, 2)
print(`10 / 2 ok={ok} result={result}`)

local ok2, err = pcall(safeDiv, 10, 0)
print(`10 / 0 ok={ok2} err={err}`)

-- -- numeric-for with negative step ----------------------------------------
local countdown = {}
for i = 5, 1, -1 do
    countdown[#countdown + 1] = tostring(i)
end
print(`countdown: {table.concat(countdown, " ")}`)

print("user.luau done")
