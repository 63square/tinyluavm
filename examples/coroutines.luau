-- Coroutines work transparently because the macro-VM delegates to the host
-- coroutine library.
local function gen()
    for i = 1, 5 do
        coroutine.yield(i * 10)
    end
end

local co = coroutine.create(gen)
while true do
    local ok, v = coroutine.resume(co)
    if not ok or v == nil then break end
    print("got", v)
end
