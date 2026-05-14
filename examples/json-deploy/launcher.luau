--!nocheck
-- All-JSON-deploy launcher for tinyvm.
--
-- The driver predecodes the macro-VM and the user program together into
-- a single JSON document of shape:
--
--   {"m": [macroK, macroF], "u": [userK, userF]}
--
-- The launcher decodes that one string with a small JSON parser and hands
-- the resulting table to the micro-VM as its `inputData` argument.
--
-- Everything tinyvm consumes from us is plain Lua data: numbers, strings,
-- booleans, nil, tables. No userdata, no opaque blobs.
local micro    = require("./tinyvm")
local decode   = require("./jsondec")

-- The driver wrapped the JSON document in a 1-element table so it could
-- come through `require()` (which rejects modules whose body returns a
-- bare string). Replace this with whatever channel makes sense for you:
-- HttpService:GetAsync, an asset, a string literal pasted at build time.
local inputData = decode(require("./payload-json")[1])

-- The env the user program sees as `_G`. A writable shadow of `_G` is
-- usually fine; restrict or extend as needed.
local userEnv = setmetatable({}, {__index = _G})
userEnv._G = userEnv
userEnv.hostInfo = {
    appName    = "tinyvm-json-deploy-example",
    appVersion = "1.0",
}

-- The shadow env exposes the op-helper functions the predecoder rewrote
-- BinOp/UnOp atoms into. The fallthrough chain is:
--   shadowEnv -> userEnv -> _G
local shadowEnv = setmetatable({
    B1  = function(a, b) return a + b  end,
    B2  = function(a, b) return a - b  end,
    B3  = function(a, b) return a * b  end,
    B4  = function(a, b) return a / b  end,
    B5  = function(a, b) return a // b end,
    B6  = function(a, b) return a %  b end,
    B7  = function(a, b) return a ^  b end,
    B8  = function(a, b) return a .. b end,
    B9  = function(a, b) return a == b end,
    B10 = function(a, b) return a ~= b end,
    B11 = function(a, b) return a <  b end,
    B12 = function(a, b) return a <= b end,
    B13 = function(a, b) return a >  b end,
    B14 = function(a, b) return a >= b end,
    U1  = function(a) return -a end,
    U2  = function(a) return not a end,
    U3  = function(a) return #a end,
}, {__index = userEnv})

-- micro(env, inputData, userEnv, label)
--   env       - the env the macro-VM uses for its own globals + helpers
--   inputData - {m = macro-VM AST, u = user-program AST}
--   userEnv   - what user code sees as its _G
--   label     - chunk name shown in diagnostic messages
print("== launcher: running user.luau (all data plane is JSON) ==")
local ok, err = pcall(micro, shadowEnv, inputData, userEnv, "user.luau")
if not ok then
    print("== launcher: user program raised an error ==")
    print(tostring(err))
else
    print("== launcher: user program finished cleanly ==")
end
