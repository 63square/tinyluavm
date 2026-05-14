-- minimal demo
local function fib(n: number): number
    if n < 2 then return n end
    return fib(n - 1) + fib(n - 2)
end

local t = {}
for i = 1, 10 do
    t[i] = fib(i)
end

local sum = 0
for _, v in ipairs(t) do
    sum += v
end

print(`fib sums = {sum}`)
return sum
