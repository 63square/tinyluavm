-- Classic recursive fibonacci.
local function fib(n: number): number
    if n < 2 then return n end
    return fib(n - 1) + fib(n - 2)
end

for i = 0, 12 do
    print(`fib({i}) = {fib(i)}`)
end
