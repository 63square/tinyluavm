-- Closures and upvalue capture.
local function makeCounter(start: number?): () -> number
    local n = start or 0
    return function()
        n += 1
        return n
    end
end

local a = makeCounter()
local b = makeCounter(100)

for _ = 1, 3 do print("a:", a()) end
for _ = 1, 3 do print("b:", b()) end
