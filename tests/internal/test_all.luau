-- Comprehensive feature test. Each `check` prints PASS or FAIL.
local pass, fail = 0, 0
local function check(name, got, want)
    local ok = got == want
    if ok then pass += 1 else fail += 1 end
    print((ok and "PASS " or "FAIL ") .. name .. "  got=" .. tostring(got) .. " want=" .. tostring(want))
end

-- 1. arithmetic + locals
do
    local a, b = 3, 4
    check("arith", a*a + b*b, 25)
end

-- 2. string concat
check("concat", "foo" .. "bar" .. 1, "foobar1")

-- 3. closures + upvalues
do
    local function mkcounter()
        local n = 0
        return function() n += 1; return n end
    end
    local c = mkcounter()
    c(); c()
    check("closure", c(), 3)
end

-- 4. multi-return / multi-assign
do
    local function two() return 10, 20 end
    local a, b = two()
    check("multret a", a, 10)
    check("multret b", b, 20)
    local t = { two(), two() }  -- only last splatted
    check("table tail splat len", #t, 3)
    check("table tail splat v1", t[1], 10)
    check("table tail splat v2", t[2], 10)
    check("table tail splat v3", t[3], 20)
end

-- 5. varargs
do
    local function sum(...)
        local s = 0
        for _, v in ipairs({...}) do s += v end
        return s
    end
    check("varargs", sum(1,2,3,4,5), 15)
end

-- 6. generic for (ipairs)
do
    local t = {10, 20, 30}
    local s = 0
    for i, v in ipairs(t) do s += i * v end
    check("gen for", s, 1*10 + 2*20 + 3*30)
end

-- 7. numeric for with step
do
    local s = 0
    for i = 10, 1, -2 do s += i end
    check("num for step", s, 10+8+6+4+2)
end

-- 8. while + break + continue
do
    local s, i = 0, 0
    while i < 10 do
        i += 1
        if i % 2 == 0 then continue end
        if i > 7 then break end
        s += i
    end
    check("while+break+continue", s, 1+3+5+7)
end

-- 9. repeat-until reads local from body
do
    local i = 0
    repeat
        local x = i * 2
        i += 1
    until x >= 6
    check("repeat-until body local", i, 4)
end

-- 10. method calls + self
do
    local o = { v = 5 }
    function o:add(x) return self.v + x end
    check("method", o:add(3), 8)
end

-- 11. metatables / __index / __add
do
    local mt = { __add = function(a, b) return {v = a.v + b.v} end }
    local a = setmetatable({v = 2}, mt)
    local b = setmetatable({v = 3}, mt)
    local c = a + b
    check("metatable __add", c.v, 5)
end

-- 12. pcall captures errors
do
    local ok, err = pcall(function() error("nope") end)
    check("pcall ok", ok, false)
    check("pcall err", string.find(err, "nope") ~= nil, true)
end

-- 13. coroutine
do
    local co = coroutine.create(function(x)
        coroutine.yield(x + 1)
        coroutine.yield(x + 2)
        return x + 3
    end)
    local ok1, v1 = coroutine.resume(co, 10)
    local ok2, v2 = coroutine.resume(co)
    local ok3, v3 = coroutine.resume(co)
    check("co1", v1, 11)
    check("co2", v2, 12)
    check("co3", v3, 13)
end

-- 14. if expression
do
    local x = if 5 > 3 then "yes" else "no"
    check("if expr", x, "yes")
end

-- 15. string interp
do
    local n = 7
    check("interp", `value={n}!`, "value=7!")
end

-- 16. compound assign to table field (single eval)
do
    local calls = 0
    local function getobj() calls += 1; return {v = 10} end
    local o = getobj()
    o.v += 5
    check("compound table field", o.v, 15)
end

-- 17. nested closures share upvalue
do
    local function outer()
        local x = 0
        local function inc() x += 1; return x end
        local function get() return x end
        return inc, get
    end
    local inc, get = outer()
    inc(); inc(); inc()
    check("nested closure share", get(), 3)
end

-- 18. table constructor variants
do
    local t = {1, 2, [10] = "x", k = "v"; 3}
    check("tab arr 1", t[1], 1)
    check("tab arr 3", t[3], 3)
    check("tab hash", t.k, "v")
    check("tab idx", t[10], "x")
end

-- 19. recursive function
do
    local function fact(n) return if n <= 1 then 1 else n * fact(n-1) end
    check("fact", fact(6), 720)
end

-- 20. return zero values vs nil
do
    local function nope() return end
    local function nilret() return nil end
    local function multi() return 1, nil, 3 end
    check("zero return as first", (nope()), nil)
    check("nil return", (nilret()), nil)
    local a, b, c = multi()
    check("multi a", a, 1)
    check("multi b", b, nil)
    check("multi c", c, 3)
end

print(string.format("\n%d passed, %d failed", pass, fail))
return fail
