-- Edge cases
local pass, fail = 0, 0
local function check(name, got, want)
    local ok = got == want
    if ok then pass += 1 else fail += 1 end
    print((ok and "PASS " or "FAIL ") .. name .. "  got=" .. tostring(got) .. " want=" .. tostring(want))
end

-- arithmetic precedence
check("prec1", 2 + 3 * 4, 14)
check("prec2", (2 + 3) * 4, 20)
check("prec3", 2 ^ 3 ^ 2, 512) -- right assoc -> 2^(3^2)
check("concat right", "a" .. "b" .. "c", "abc")
check("neg unary", -2^2, -4) -- ^ binds tighter than unary -

-- short-circuit
check("and1", nil and error("nope"), nil)
check("or1", 5 or error("nope"), 5)
check("and2", 0 and "ok", "ok") -- 0 is truthy in Lua
check("or2", false or "fallback", "fallback")

-- equality
check("eq nil", nil == nil, true)
check("eq diff type", 1 == "1", false)
check("ne", 1 ~= 2, true)

-- table length, ipairs over holes
do
    local t = {1,2,3}
    check("len", #t, 3)
    t[5] = 5
    -- # may return 3 or 5 (border) - just don't check that
    local s = 0
    for i, v in ipairs({10,20,30}) do s = s + v end
    check("ipairs sum", s, 60)
end

-- pairs over hash
do
    local t = {a=1, b=2, c=3}
    local s = 0
    for k, v in pairs(t) do s = s + v end
    check("pairs sum", s, 6)
end

-- string methods
check("upper", ("hello"):upper(), "HELLO")
check("sub", string.sub("abcdef", 2, 4), "bcd")
check("format", string.format("%d/%s", 42, "x"), "42/x")
check("find", (string.find("hello world", "world")), 7)

-- math
check("floor", math.floor(3.7), 3)
check("sqrt", math.sqrt(16), 4)
check("max", math.max(1,5,2,4), 5)

-- nested pcall + error object
do
    local ok, err = pcall(function() error({code=42}) end)
    check("err table ok", ok, false)
    check("err table code", err.code, 42)
end

-- xpcall
do
    local function handler(e) return "handled:" .. tostring(e) end
    local ok, r = xpcall(function() error("boom") end, handler)
    check("xpcall ok", ok, false)
    check("xpcall handled prefix", string.sub(r, 1, 8), "handled:")
end

-- self-reference via _ENV-like table access
do
    _G_like_check = "hi"
    -- assign creates a global, accessible
    check("global set/get", _G_like_check, "hi")
end

-- closures with loop-iter capture
do
    local fns = {}
    for i = 1, 3 do
        local x = i
        fns[i] = function() return x end
    end
    check("loop capture 1", fns[1](), 1)
    check("loop capture 2", fns[2](), 2)
    check("loop capture 3", fns[3](), 3)
end

-- table.unpack / select
check("select n", select("#", 1,2,3,4), 4)
check("select 2", (select(2, 10,20,30)), 20)

-- divmod
check("//", 7 // 2, 3)
check("%", 7 % 3, 1)

-- string interp with multiple exprs
do
    local a, b = 3, 5
    check("interp2", `{a}+{b}={a+b}`, "3+5=8")
end

print(string.format("\n%d passed, %d failed", pass, fail))
return fail
