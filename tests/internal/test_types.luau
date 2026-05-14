--!strict
-- Comprehensive type-stripping tests. None of these should affect runtime.
local pass, fail = 0, 0
local function check(name, got, want)
    local ok = got == want
    if ok then pass += 1 else fail += 1 end
    print((ok and "PASS " or "FAIL ") .. name .. " got=" .. tostring(got) .. " want=" .. tostring(want))
end

-- 1. type alias
type Foo = number
type Bar = { x: number, y: string }
type Baz<T> = { value: T }
type Maybe<T> = T?
type Either<A, B> = A | B
type Fn = (number, string) -> (boolean, ...any)
type FnGeneric<T, U> = <V>(T, U, V) -> V
type Indexer = { [string]: number }
type Nested = { items: { { k: number, v: string } } }
type Recursive = { next: Recursive? }
type Func = (a: number, b: string?) -> (...string)

local x = 1
check("alias doesn't affect runtime", x, 1)

-- 2. exported type alias
export type Public = string

-- 3. local var with simple type
local a: number = 5
check("typed local", a, 5)

-- 4. local var with optional type
local b: string? = nil
check("optional local", b, nil)

-- 5. local var with union type
local c: number | string = "hi"
check("union local", c, "hi")

-- 6. local var with intersection type
local d: { x: number } & { y: number } = { x = 1, y = 2 }
check("intersection local", d.x + d.y, 3)

-- 7. local var with table type
local e: { [number]: string } = { "a", "b", "c" }
check("indexer local", e[2], "b")

-- 8. local var with nested type
local f: { items: { number } } = { items = { 1, 2, 3 } }
check("nested type", f.items[3], 3)

-- 9. function with typed params and return
local function add(x: number, y: number): number
    return x + y
end
check("typed function", add(2, 3), 5)

-- 10. function with optional param
local function maybe(x: number?): number
    return x or 0
end
check("optional param", maybe(nil), 0)
check("optional param 2", maybe(42), 42)

-- 11. function with variadic typed
local function sum(...: number): number
    local s = 0
    for _, v in ipairs({...}) do s += v end
    return s
end
check("variadic typed", sum(1, 2, 3, 4), 10)

-- 12. function with multi-return type
local function multi(): (number, string)
    return 7, "ok"
end
local n, s = multi()
check("multi-ret n", n, 7)
check("multi-ret s", s, "ok")

-- 13. function with variadic return type
local function vret(): ...number
    return 1, 2, 3
end
local r1, r2, r3 = vret()
check("variadic ret", r1 + r2 + r3, 6)

-- 14. generic function
local function id<T>(x: T): T
    return x
end
check("generic id", id(42), 42)
check("generic id str", id("hello"), "hello")

-- 15. generic with multiple params
local function pair<A, B>(a: A, b: B): (A, B)
    return a, b
end
local p1, p2 = pair(1, "two")
check("generic pair 1", p1, 1)
check("generic pair 2", p2, "two")

-- 16. function-typed parameter
local function apply<T, U>(f: (T) -> U, x: T): U
    return f(x)
end
check("function-typed param", apply(function(x: number): number return x * 2 end, 5), 10)

-- 17. type cast with ::
local cast = (42 :: any) :: number
check("type cast", cast, 42)

-- 18. type cast in expression
local complex = ("123" :: string) .. ("456" :: string)
check("type cast in expr", complex, "123456")

-- 19. type cast on function result
local function strNum(): string
    return "42"
end
local num = (tonumber(strNum() :: string) :: number)
check("type cast on call", num, 42)

-- 20. method with typed self (via colon syntax)
local obj = { v = 10 }
function obj.add(self, x: number): number
    return self.v + x
end
check("typed method", obj:add(5), 15)

-- 21. method with self (colon decl) and typed params
local obj2 = { name = "lua" }
function obj2:greet(other: string): string
    return self.name .. "+" .. other
end
check("method colon decl", obj2:greet("u"), "lua+u")

-- 22. function returning function type
local function counter(): () -> number
    local n = 0
    return function(): number
        n += 1
        return n
    end
end
local c1 = counter()
c1(); c1()
check("function returning function", c1(), 3)

-- 23. table literal with type field syntax (not standard but harmless)
local typed_table = { x = 1 :: number, y = 2 :: number }
check("inline cast in table", typed_table.x + typed_table.y, 3)

-- 24. union with literal types (string singletons)
type Direction = "left" | "right" | "up" | "down"
local dir: Direction = "left"
check("string singleton union", dir, "left")

-- 25. type with parens
local pp: (number) = 7
check("paren type", pp, 7)

-- 26. typeof in type position
local zz = { a = 1, b = 2 }
local copy: typeof(zz) = { a = 5, b = 10 }
check("typeof type", copy.a + copy.b, 15)

-- 27. nested generic
local function wrap<T>(x: T): { value: T }
    return { value = x }
end
check("nested generic", wrap(99).value, 99)

-- 28. complex compound return type
local function complexRet(): { [string]: number }
    return { a = 1, b = 2 }
end
check("complex ret", complexRet().a + complexRet().b, 3)

-- 29. local function with type
local function noop(): ()
end
noop()
check("noop returns nothing", (noop()), nil)

-- 30. assert with type cast
local function intify(s: string): number
    return assert(tonumber(s) :: number)
end
check("assert cast", intify("42"), 42)

print(string.format("\n%d passed, %d failed", pass, fail))
return fail
