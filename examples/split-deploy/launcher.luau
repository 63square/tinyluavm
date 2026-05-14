--!nocheck
-- Split-deploy launcher for tinyvm.
--
-- This is what you write yourself when you want to ship the micro-VM source
-- separately from the macro-VM AST and the user program. It loads three
-- Luau modules:
--
--   1. ./tinyvm        -- the micro-VM (a function)
--   2. ./macrovm-ast   -- the pre-decoded macro-VM AST  (returns {K, F})
--   3. ./user-ast      -- the pre-decoded user program  (returns {K, F})
--
-- combines (2) and (3) into the `inputData` table the micro-VM expects,
-- and wires up the shadow environment so the op-helper functions the
-- predecoder rewrote BinOp/UnOp into resolve correctly.
--
-- In a real Roblox project the three modules would live anywhere -- in
-- this example they're laid out flat next to this file so plain
-- `require("./...")` works.
local micro   = require("./tinyvm")
local mvmAst  = require("./macrovm-ast")  -- returns {K, F}
local userAst = require("./user-ast")     -- returns {K, F}

-- The inputData payload. The micro-VM expects `D.m` to be the macro-VM
-- AST `{K, F}` and `D.u` to be the user program AST `{K, F}`.
local inputData = {m = mvmAst, u = userAst}

-- ---------------------------------------------------------------------------
-- Build the env the *user program* sees as its globals. A writable shadow
-- of _G is usually what you want: the user can read everything stdlib
-- gives them, and writes don't leak into the host's _G.
-- ---------------------------------------------------------------------------
local userEnv = setmetatable({}, {__index = _G})
userEnv._G = userEnv

-- Anything you stick on `userEnv` is visible to the user program as a
-- global. Anything you *don't* add and that's not on `_G` is invisible.
userEnv.hostInfo = {
    appName    = "tinyvm-split-deploy-example",
    appVersion = "1.0",
}

-- ---------------------------------------------------------------------------
-- Build the env the *macro-VM* uses internally. It needs:
--   * stdlib globals it references (table.pack, getmetatable, error, ...)
--     -- via __index fallthrough
--   * the B1..B14 / U1..U3 helpers that the predecoder rewrote arithmetic
--     atoms into -- defined here
-- ---------------------------------------------------------------------------
local shadowEnv = setmetatable({
    B1  = function(a, b) return a + b  end,
    B2  = function(a, b) return a - b  end,
    B3  = function(a, b) return a * b  end,
    B4  = function(a, b) return a / b  end,
    B5  = function(a, b) return a // b end,
    B6  = function(a, b) return a % b  end,
    B7  = function(a, b) return a ^ b  end,
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

-- ---------------------------------------------------------------------------
-- Run the user program.
--
-- Signature: micro(env, inputData, userEnv, label)
--   env         - the env the macro-VM uses (shadowEnv: op helpers + fallthrough)
--   inputData   - {m = macro-VM AST, u = user program AST}
--   userEnv     - what the user program sees as its _G
--   label       - chunk name shown in diagnostic messages
-- ---------------------------------------------------------------------------
print("== launcher: starting user program ==")
local ok, err = pcall(micro, shadowEnv, inputData, userEnv, "user.luau")
if not ok then
    print("== launcher: user program raised an error ==")
    print(tostring(err))
else
    print("== launcher: user program finished cleanly ==")
end
