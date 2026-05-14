-- Sample user program for the http-deploy example. The launcher fetched
-- the combined macro-VM + this program AST over HTTP, decoded it, and
-- handed the result to the micro-VM.

print(`hello from {hostInfo.appName}`)
print(`served by   : {hostInfo.serverInfo}`)
print(`fetched from: {hostInfo.fetchedUrl}`)
print(`payload size: {hostInfo.payloadBytes} bytes`)
print("")

-- A small useful thing: compute the first N primes.
local function primesBelow(limit: number)
    local out = {}
    for n = 2, limit do
        local prime = true
        for d = 2, math.floor(math.sqrt(n)) do
            if n % d == 0 then prime = false; break end
        end
        if prime then out[#out + 1] = n end
    end
    return out
end

local ps = primesBelow(50)
print(`primes below 50 ({#ps} total): {table.concat(ps, ", ")}`)

-- Closure-based accumulator just to exercise the macro-VM's upvalue path.
local function summer()
    local s = 0
    return function(x)
        s += x
        return s
    end
end

local acc = summer()
for _, p in ipairs(ps) do acc(p) end
print(`sum of those primes: {acc(0)}`)

print("user.luau done")
